"""Text evaluation models.

Handles two categories of text assessment model:

Sequence classification -- scores text against a fixed label set. The output
is a list of EvalScore with label and score fields. Compatible with sentiment,
toxicity, topic classification, and similar models.
    unitary/toxic-bert
    distilbert-base-uncased-finetuned-sst-2-english
    cardiffnlp/twitter-roberta-base-sentiment

Token classification -- identifies and scores labelled spans within text.
The output is a list of EvalScore with entity_group, score, word, start,
and end fields. Compatible with NER and PII detection models.
    openai/privacy-filter
    dslim/bert-base-NER
    dslim/bert-large-NER

Both categories share the same model type (text-eval), request model
(EvalTextRequest), and route (/eval/text). The caller distinguishes the
two output shapes by the presence of entity_group vs label on each item.
"""

import logging
import os
from time import perf_counter as clock

import torch
from api.models import EvalResponse, EvalScore, EvalTextRequest
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def _is_token_classification(model) -> bool:
    """Return True if the loaded model is a token classifier.

    Token classifiers produce per-token logits decoded into spans.
    Sequence classifiers produce per-sequence logits decoded into scores.
    """
    return "TokenClassification" in type(model).__name__


def load_text_eval(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Load a text evaluation model.

    Tries AutoModelForTokenClassification first. Falls back to
    AutoModelForSequenceClassification if the model does not support
    token classification. This covers NER and sequence classifier
    checkpoints without requiring the caller to specify the architecture.
    """
    from transformers import (AutoModelForSequenceClassification,
                              AutoModelForTokenClassification)
    from transformers import AutoTokenizer as T
    try:
        return standard_loader(T, AutoModelForTokenClassification, modelname, cache_dir=cache_dir, **kwargs)
    except Exception:
        return standard_loader(T, AutoModelForSequenceClassification, modelname, cache_dir=cache_dir, **kwargs)


@model_spec(
    model_type=ModelType.TEXT_EVAL,
    mode=ModelMode.EVAL,
    output_fields=[],
    loader=load_text_eval,
    request_model=EvalTextRequest,
    response_model=EvalResponse,
    route="/eval/text",
)
class TextEvalModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self._token_classification = _is_token_classification(self.model)

    def _run(
        self, user_id: str, message_id: str, request: EvalTextRequest
    ) -> EvalResponse:
        if self._token_classification:
            return self._run_token_classification(user_id, message_id, request)
        return self._run_sequence_classification(user_id, message_id, request)

    def _run_sequence_classification(
        self, user_id: str, message_id: str, request: EvalTextRequest
    ) -> EvalResponse:
        T = clock()

        inputs = self.processor(
            request.text,
            return_tensors="pt",
            truncation=True,
            padding=True,
        )
        input_tokens = inputs.input_ids.nelement()

        T1 = clock()
        with torch.no_grad():
            outputs = self.model(**inputs)
        iduration = clock() - T1

        probs = torch.softmax(outputs.logits, dim=-1)[0]
        scores = [
            EvalScore(
                label=self.model.config.id2label[i],
                score=round(probs[i].item(), 4),
            )
            for i in range(len(probs))
        ]

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' scores=%s in %.2fs (inference %.2fs)",
            user_id, message_id, self.modelname,
            str(scores), duration, iduration,
        )

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.TEXT_EVAL,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        return EvalResponse(model=self.modelname, scores=scores, usage=usage)

    def _run_token_classification(
        self, user_id: str, message_id: str, request: EvalTextRequest
    ) -> EvalResponse:
        """Run token classification inference and return decoded spans.

        Uses the transformers pipeline with aggregation_strategy='simple'
        which merges B/I/E/S tokens into coherent entity spans.
        """
        from transformers import pipeline as hf_pipeline

        T = clock()

        inputs = self.processor(
            request.text,
            return_tensors="pt",
            truncation=True,
        )
        input_tokens = inputs.input_ids.nelement()

        T1 = clock()
        ner = hf_pipeline(
            task="token-classification",
            model=self.model,
            tokenizer=self.processor,
            aggregation_strategy="simple",
        )
        spans = ner(request.text)
        iduration = clock() - T1

        scores = [
            EvalScore(
                entity_group=s["entity_group"],
                score=round(float(s["score"]), 4),
                word=s["word"],
                start=s["start"],
                end=s["end"],
            )
            for s in spans
        ]

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' found %d spans in %.2fs (inference %.2fs)",
            user_id, message_id, self.modelname,
            len(scores), duration, iduration,
        )

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.TEXT_EVAL,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
        )

        return EvalResponse(model=self.modelname, scores=scores, usage=usage)
