"""
Marigold pump.

Usage:
    python3 -m tools.pump pump   [--once] [--interval N] [--concurrency N]
                                 [--types a,b] [--skip-types a,b]
                                 [--order grouped|random|interleaved]
                                 [--requests N] [--jitter N]

    python3 -m tools.pump audit  [--date YYYY-MM-DD] [--days N] [--force]
                                 [--poll] [--report]
"""

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional
import fnmatch

import httpx

from tools.dashboard.config import API_BASE, API_HEADERS
from tools.dashboard.history import write_entry

log = logging.getLogger("pump")
logging.getLogger("httpx").setLevel("WARNING")

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

JOB_INTERVAL_S  = 30
DEFAULT_CONCURRENCY = 64


# ---------------------------------------------------------------------------
# Sample inputs  (unchanged)
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
    ("Inflation rose sharply in Q3.", "Consumer prices increased between July and September."),
    ("The model failed to converge.", "Training did not complete successfully."),
]


# ---------------------------------------------------------------------------
# Route map
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
    return {"model": model, "text": random.choice(EVAL_TEXTS), "nonce": nonce}

def _make_similarity(model: str, nonce: str) -> dict:
    pair = random.choice(SIMILARITY_PAIRS)
    return {"model": model, "text_a": pair[0], "text_b": pair[1], "nonce": nonce}

ROUTE_MAP: Dict[str, tuple] = {
    "instruct":         ("/gen/instruct",          "instruct",         _make_instruct),
    "text-embedding":   ("/embed/text",             "text-embedding",   _make_embedding),
    "tts":              ("/gen/tts",                "tts",              _make_tts),
    "text-eval":        ("/eval/text",              "text-eval",        _make_text_eval),
    "text-similarity":  ("/eval/text-similarity",   "text-similarity",  _make_similarity),
}


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

@dataclass
class Job:
    model_name: str
    model_type: str
    endpoint:   str
    nonce:      str


def _model_matches(name: str, patterns: set) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _build_jobs(
    models:             Dict[str, List[str]],
    skip_types:         List[str],
    only_types:         List[str],
    only_models:        List[str],
    requests_per_model: int  = 1,
    order:              str  = "grouped",
) -> List[Job]:
    """
    Build the job list with ordering control.

    grouped:     all jobs for model A, then model B, etc.
                 Produces deep per-model queue bursts; task_runner scales
                 each model to its estimated worker count immediately.

    random:      jobs shuffled uniformly.
                 All models get triggered roughly simultaneously; good
                 for realistic mixed-load testing.

    interleaved: round-robin across models.
                 Each model gets one request before any model gets a second;
                 maximises the number of distinct task_runner launches in
                 the first pass.
    """
    skip        = set(skip_types)
    only        = set(only_types)
    only_models = set(only_models)

    # Build per-model buckets
    buckets: Dict[str, List[Job]] = {}
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
            if not _model_matches(name, only_models):
                continue
            key = f"{model_type}/{name}"
            for _ in range(requests_per_model):
                nonce = uuid.uuid4().hex[:8]
                buckets.setdefault(key, []).append(Job(
                    model_name = name,
                    model_type = model_type,
                    endpoint   = endpoint,
                    nonce      = nonce,
                ))

    if order == "grouped":
        jobs = [job for bucket in buckets.values() for job in bucket]

    elif order == "random":
        jobs = [job for bucket in buckets.values() for job in bucket]
        random.shuffle(jobs)

    elif order == "interleaved":
        # Round-robin: one job from each model per pass until all buckets empty
        lists   = list(buckets.values())
        indices = [0] * len(lists)
        jobs    = []
        while True:
            added = False
            for i, lst in enumerate(lists):
                if indices[i] < len(lst):
                    jobs.append(lst[indices[i]])
                    indices[i] += 1
                    added = True
            if not added:
                break

    else:
        raise ValueError(f"unknown order '{order}': use grouped, random, or interleaved")

    return jobs


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------

def fetch_models() -> Dict[str, List[str]]:
    try:
        import requests as _requests
        r = _requests.get(f"{API_BASE}/models.json", headers=API_HEADERS, timeout=10)
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
# Async submission
# ---------------------------------------------------------------------------

async def _submit_one(
    client:  httpx.AsyncClient,
    sem:     asyncio.Semaphore,
    job:     Job,
    pump_id: str,
) -> Optional[tuple]:
    route = ROUTE_MAP.get(job.model_type)
    if not route:
        return None
    _, _, factory = route
    payload = factory(job.model_name, job.nonce)

    async with sem:
        try:
            r = await client.post(
                f"{API_BASE}{job.endpoint}",
                json=payload,
                timeout=15.0,
            )
        except httpx.RequestError as e:
            log.error("[%s/%s] submit error: %s", job.model_type, job.model_name, e)
            return None

    if r.status_code != 200:
        log.error(
            "[%s/%s] submit failed: %s %s",
            job.model_type, job.model_name,
            r.status_code, r.text[:120],
        )
        return None

    message_id = r.json().get("message_id")
    if not message_id:
        return None

    return message_id, job.model_name, job.model_type, job.nonce, pump_id


async def _dispatch_async(jobs: List[Job], concurrency: int, pump_id: str) -> None:
    log.info("dispatching %d job(s) concurrency=%d", len(jobs), concurrency)
    sem = asyncio.Semaphore(concurrency)

    limits = httpx.Limits(
        max_connections           = concurrency,
        max_keepalive_connections = concurrency,
    )

    async with httpx.AsyncClient(headers=API_HEADERS, limits=limits) as client:
        raw = await asyncio.gather(*[
            _submit_one(client, sem, job, pump_id)
            for job in jobs
        ])

    results = [r for r in raw if r is not None]
    failed  = len(jobs) - len(results)

    log.info(
        "submitted %d/%d  failed=%d",
        len(results), len(jobs), failed,
    )

    loop = asyncio.get_running_loop()
    await asyncio.gather(*[
        loop.run_in_executor(None, write_entry, mid, mn, mt, n, pid)
        for mid, mn, mt, n, pid in results
    ])


def dispatch(jobs: List[Job], concurrency: int = DEFAULT_CONCURRENCY, pump_id: str = "") -> None:
    asyncio.run(_dispatch_async(jobs, concurrency, pump_id))


# ---------------------------------------------------------------------------
# Subcommand handler
# ---------------------------------------------------------------------------

def cmd_pump(args) -> None:
    pump_id = uuid.uuid4().hex[:8]

    log.info(
        "pump id=%s  API=%s  interval=%ds  concurrency=%d  order=%s  rounds=%s",
        pump_id, API_BASE, args.interval, args.concurrency, args.order,
        args.rounds if args.rounds else "unlimited",
    )

    models        = {}
    refresh_every = 10
    round_num     = 0

    while True:
        if round_num % refresh_every == 0:
            models = fetch_models()

        jobs = _build_jobs(
            models,
            skip_types         = [t.strip() for t in args.skip_types.split(",") if t.strip()],
            only_types         = [t.strip() for t in args.types.split(",")      if t.strip()],
            only_models        = [m.strip() for m in args.models.split(",")     if m.strip()],
            requests_per_model = args.requests,
            order              = args.order,
        )

        if not jobs:
            log.warning("no jobs -- check API and ROUTE_MAP")
            break

        t0 = time.time()
        dispatch(jobs, concurrency=args.concurrency, pump_id=pump_id)
        log.info("round %d: %d job(s) in %.1fs", round_num + 1, len(jobs), time.time() - t0)

        round_num += 1

        if args.once or (args.rounds and round_num >= args.rounds):
            break

        time.sleep(args.interval)
