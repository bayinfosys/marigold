"""
Marigold pump.

Usage:
    python3 -m tools.pump pump   [--once] [--interval N] [--workers N]
                                 [--types a,b] [--skip-types a,b]

    python3 -m tools.pump audit  [--date YYYY-MM-DD] [--days N] [--force]
                                 [--poll] [--report]

    # default (no subcommand) runs pump for backwards compatibility
    python3 -m tools.pump --once
"""

import logging
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from tools.dashboard.config import API_BASE, API_HEADERS
from tools.dashboard.history import write_entry

log = logging.getLogger("pump")

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

POLL_INTERVAL_S = 3
POLL_MAX_RETRIES = 120
MAX_WORKERS = 16
JOB_INTERVAL_S = 30


# ---------------------------------------------------------------------------
# Sample inputs
# ---------------------------------------------------------------------------

INSTRUCT_PROMPTS = [
    "Explain the difference between supervised and unsupervised learning in two sentences.",
    "What are the main advantages of deploying AI on private UK infrastructure?",
    "Describe the PageRank algorithm briefly.",
    "What is a transformer architecture in neural networks?",
    "List three use cases for text embedding models.",
    "What is the purpose of a message queue in a distributed system?",
    "Describe what a vector database is and what it is used for.",
    "What is the difference between precision and recall in a classification task?",
    "Explain what tokenisation is in the context of large language models.",
    "What is the difference between batch and stream processing?",
]

EMBED_TEXTS = [
    "Private AI inference on AWS infrastructure with UK data residency.",
    "Open-weight model hosting with ECS autoscaling and SQS job queues.",
    "FCA-regulated firms require explainable AI with full audit trails.",
    "Retrieval-augmented generation with private embedding infrastructure.",
    "Automated document classification for compliance workflows.",
    "Named entity recognition over financial disclosure documents.",
]

TTS_TEXTS = [
    "Marigold provides private AI inference on UK infrastructure.",
    "Open-weight models hosted on your own AWS account.",
    "Regulatory compliance begins with knowing where your AI runs.",
]

EVAL_TEXTS = [
    "This product has significantly improved our workflow efficiency.",
    "The service was disappointing and did not meet expectations.",
    "Outstanding results across every benchmark we tested.",
]

SIMILARITY_PAIRS = [
    ("The cat sat on the mat.", "A cat was resting on a rug."),
    (
        "Inflation rose sharply in Q3.",
        "Consumer prices increased between July and September.",
    ),
    ("The model failed to converge.", "Training did not complete successfully."),
]


# ---------------------------------------------------------------------------
# Route map
# Inferred from model type: (endpoint, mode, task, payload_factory)
# ---------------------------------------------------------------------------


def _make_instruct(model: str, nonce: str) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": random.choice(INSTRUCT_PROMPTS)}],
        "max_tokens": 200,
        "temperature": 0.7,
        "nonce": nonce,
    }


def _make_embedding(model: str, nonce: str) -> dict:
    return {
        "model": model,
        "input": random.choice(EMBED_TEXTS),
        "quantization": "float32",
        "precision": 4,
        "nonce": nonce,
    }


def _make_tts(model: str, nonce: str) -> dict:
    return {
        "model": model,
        "text": random.choice(TTS_TEXTS),
        "language_code": "en-gb",
        "nonce": nonce,
    }


def _make_text_eval(model: str, nonce: str) -> dict:
    return {
        "model": model,
        "text": random.choice(EVAL_TEXTS),
        "nonce": nonce,
    }


def _make_similarity(model: str, nonce: str) -> dict:
    pair = random.choice(SIMILARITY_PAIRS)
    return {
        "model": model,
        "text_a": pair[0],
        "text_b": pair[1],
        "nonce": nonce,
    }


ROUTE_MAP: Dict[str, tuple] = {
    "instruct": ("/gen/instruct", "instruct", _make_instruct),
    "text-embedding": ("/embed/text", "text-embedding", _make_embedding),
    "tts": ("/gen/tts", "tts", _make_tts),
    "text-eval": ("/eval/text", "text-eval", _make_text_eval),
    "text-similarity": ("/eval/text-similarity", "text-similarity", _make_similarity),
}


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class Job:
    model_name: str
    model_type: str
    endpoint: str
    nonce: str


def _build_jobs(
    models:            Dict[str, List[str]],
    skip_types:        List[str],
    only_types:        List[str],
    requests_per_model: int = 1,
) -> List[Job]:
    skip = set(skip_types)
    only = set(only_types)
    jobs = []

    for model_type, model_names in sorted(models.items()):
        if model_type in skip:
            continue
        if only and model_type not in only:
            continue
        route = ROUTE_MAP.get(model_type)
        if not route:
            log.debug("no route for model type %s -- skipping", model_type)
            continue
        endpoint, _, _ = route
        for name in model_names:
            for _ in range(requests_per_model):
                nonce = uuid.uuid4().hex[:8]    # unique nonce per request
                jobs.append(Job(
                    model_name = name,
                    model_type = model_type,
                    endpoint   = endpoint,
                    nonce      = nonce,
                ))

    return jobs


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


def fetch_models() -> Dict[str, List[str]]:
    try:
        r = requests.get("%s/models.json" % API_BASE, headers=API_HEADERS, timeout=10)
        if r.status_code != 200:
            log.warning("GET /models.json: %s [%s]", r.status_code, r.text)
            return {}
        result: Dict[str, List[str]] = {}
        for _hash, m in r.json().items():
            mtype = m.get("type", "")
            mname = (m.get("name") or "").lower()
            if mtype and mname:
                result.setdefault(mtype, []).append(mname)
        total = sum(len(v) for v in result.values())
        log.info("discovered %d models across %d type(s)", total, len(result))
        return result
    except Exception as e:
        log.warning("fetch_models: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Submit + history
# ---------------------------------------------------------------------------


def submit_job(job: Job, pump_id: str = "") -> Optional[str]:
    route = ROUTE_MAP.get(job.model_type)
    if not route:
        return None
    _, _, factory = route
    payload = factory(job.model_name, job.nonce)

    try:
        r = requests.post(
            "%s%s" % (API_BASE, job.endpoint),
            json=payload,
            headers=API_HEADERS,
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        log.error("[%s/%s] submit error: %s", job.model_type, job.model_name, e)
        return None

    if r.status_code != 200:
        log.error(
            "[%s/%s] submit failed: %s %s",
            job.model_type,
            job.model_name,
            r.status_code,
            r.text[:120],
        )
        return None

    message_id = r.json().get("message_id")
    if message_id:
        log.info(
            "[%s/%s] submitted  id=%s",
            job.model_type,
            job.model_name,
            message_id,
        )
        write_entry(
            message_id=message_id,
            model_name=job.model_name,
            model_type=job.model_type,
            nonce=job.nonce,
            pump_id=pump_id
        )

    return message_id


def _run_job(job: Job, jitter: int = 0, pump_id: str = "") -> None:
    """Submit a job. Fire and forget -- poll via dashboard or job_audit."""
    if jitter > 0:
        time.sleep(random.uniform(0, jitter))
    submit_job(job, pump_id=pump_id)


def dispatch(jobs: List[Job], workers: int, jitter: int = 0, pump_id: str = "") -> None:
    log.info("dispatching %d job(s) with up to %d workers", len(jobs), workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_job, job, jitter, pump_id): job for job in jobs}
        for future in as_completed(futures):
            exc = future.exception()
            if exc:
                log.error("[%s] unhandled: %s", futures[future].model_name, exc)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_pump(args) -> None:
    pump_id = uuid.uuid4().hex[:8]

    log.info("pump id=%s  API=%s  interval=%ds  workers=%d  rounds=%s",
             pump_id, API_BASE, args.interval, args.workers,
             args.rounds if args.rounds else "unlimited")

    models        = {}
    refresh_every = 10
    round_num     = 0

    while True:
        if round_num % refresh_every == 0:
            models = fetch_models()

        jobs = _build_jobs(
            models,
            skip_types = [t.strip() for t in args.skip_types.split(",") if t.strip()],
            only_types = [t.strip() for t in args.types.split(",") if t.strip()],
            requests_per_model = args.requests,
        )

        if not jobs:
            log.warning("no jobs -- check API and ROUTE_MAP")
            break

        t0 = time.time()
        dispatch(jobs, args.workers, jitter=args.jitter, pump_id=pump_id)
        log.info("round %d: %d job(s) in %.1fs",
                 round_num + 1, len(jobs), time.time() - t0)

        round_num += 1

        if args.once or (args.rounds and round_num >= args.rounds):
            break

        time.sleep(args.interval)


        if not jobs:
            log.warning("no jobs -- check API and ROUTE_MAP")
            break
