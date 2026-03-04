"""Text evaluation models.

Scores a single text string against model-specific metrics. The set of
scores returned depends on the checkpoint -- a toxicity model returns
toxicity/non-toxicity probabilities, a sentiment model returns
positive/negative/neutral, and so on. Labels are taken from the model's
own config.id2label mapping.

Compatible models:
    unitary/toxic-bert
    distilbert-base-uncased-finetuned-sst-2-english
    cardiffnlp/twitter-roberta-base-sentiment
"""

import logging
import os
from time import perf_counter as clock

import torch

from shared.enums import ModelMode, ModelType
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage
from models.standard_loader import ModelLoaderResult, standard_loader
from api.models import EvalResponse, EvalTextRequest

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def load_text_eval(modelname: str, **kwargs) -> ModelLoaderResult:
    """Sequence classification models for text scoring."""
    from transformers import AutoTokenizer as T
    from transformers import AutoModelForSequenceClassification as M
    return standard_loader(T, M, modelname, **kwargs)


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

    def _run(
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
        scores = {
            self.model.config.id2label[i]: round(probs[i].item(), 4)
            for i in range(len(probs))
        }

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' scores=%s in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            str(scores),
            duration,
            iduration,
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
