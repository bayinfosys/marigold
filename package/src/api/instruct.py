"""call the instruct endpoints"""
import requests
import logging

from .models import InstructRequest, InstructResponse


logger = logging.getLogger(__name__)


class Instruct(InstructRequest):
    """encapsualte the instruct endpoints"""
    endpoint_url: str

    def __call__(self) -> InstructResponse:
        """call the endpoint with this request"""
        # FIXME: limit to fields in the InstructRequest
        obj = self.model_dump(exclude_defaults=True, exclude_unset=True)

        logger.info("submitting '%s' to '%s'", str(obj), self.endpoint_url)

        try:
            r = requests.post(self.endpoint_url, json=obj)
        except Exception as e:
            logger.error("failed to submit request to '%s' [%s]", str(self.endpoint_url), str(e))
            return

        if not r.ok:
            logger.error("[%03i] %s", r.status_code, r.text)
            return

        logger.info("[%03i] %s", r.status_code, r.text)

        response: InstructResponse = InstructResponse(**r.json())
        return response
