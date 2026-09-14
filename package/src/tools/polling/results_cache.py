import json
import logging

from dynawrap.backends.base import DBBackend
from shared.db_models import ResultsItem
from shared.enums import StatusCode


logger = logging.getLogger(__name__)


class ResultsCache:
    """Backend-agnostic wrapper for job result storage.

    Replaces the module-level DynamoDB calls in cache.py with an
    injected DBBackend. Accepts any dynawrap-compatible backend.
    """

    def __init__(self, backend: DBBackend, table: str):
        self._backend = backend
        self._table = table

    def create(self, user_id: str, message_id: str, status: str = "queued", status_code: StatusCode = StatusCode.OK) -> None:
        item = ResultsItem(
            user_id=user_id,
            job_id=message_id,
            status=status,
            code=status_code,
            ttl=ResultsItem.make_ttl(),
        )
        self._backend.save(self._table, item)

    def get_status(self, user_id: str, message_id: str) -> str | None:
        item = self._backend.get(
            self._table,
            ResultsItem,
            user_id=user_id,
            job_id=message_id,
        )
        return item.status if item else None

    def get_response(self, user_id: str, message_id: str) -> dict:
        item = self._backend.get(
            self._table,
            ResultsItem,
            user_id=user_id,
            job_id=message_id,
        )
        if item is None or item.response is None:
            return {}
        return json.loads(item.response)

    def get_code(self, user_id: str, message_id: str) -> StatusCode | None:
        """Status code for a job, or None if the record is absent.

        Written by create() at submission and by write_error() on failure.
        Distinct from `status`: status says whether the job finished, code
        says why it ended as it did.
        """
        item = self._backend.get(
            self._table,
            ResultsItem,
            user_id=user_id,
            job_id=message_id,
        )
        return item.code if item else None

    def update_status(self, user_id: str, message_id: str, status: str) -> None:
        item = self._backend.get(
            self._table,
            ResultsItem,
            user_id=user_id,
            job_id=message_id,
        )
        if item is None:
            return
        self._backend.save(self._table, item.model_copy(update={"status": status}))

    def delete(self, user_id: str, message_id: str) -> None:
        item = self._backend.get(
            self._table,
            ResultsItem,
            user_id=user_id,
            job_id=message_id,
        )
        if item is None:
            return
        self._backend.delete(self._table, item)

    def write_result(self, user_id: str, message_id: str, response: dict) -> None:
        item = self._backend.get(self._table, ResultsItem, user_id=user_id, job_id=message_id)
        if item is None:
            logger.warning("[%s/%s] results record not found", user_id, message_id)
            return
        self._backend.save(self._table, item.model_copy(update={
            "status": "complete",
            "response": json.dumps(response),
        }))

    def write_error(self, user_id: str, message_id: str, error: str,
                    code: StatusCode = StatusCode.UNSPECIFIED) -> None:
        item = self._backend.get(self._table, ResultsItem, user_id=user_id, job_id=message_id)
        if item is None:
            return
        self._backend.save(self._table, item.model_copy(update={
            "status": "error",
            "code": code,
            "response": json.dumps({"error": error}),
        }))
