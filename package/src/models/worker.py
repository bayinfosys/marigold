"""Worker loop for Marigold model inference tasks.

Three concerns, one per component.

resident_model
--------------
Residency. A context manager that loads a model, verifies it fits in
VRAM, yields it, and unloads it on the way out. Acquisition and release
share one scope, so a failure at any point after the weights land still
unloads them. Load failure leaves the scope as ModelLoadError; anything
raised while the model is in use propagates unchanged.

QueueRunner
-----------
Drainage. One model, one queue. Receives a model it did not load and
does not own. Polls until idle_timeout seconds have elapsed since the
last message, then returns. idle_timeout=-1 polls indefinitely.

ModelScheduler
--------------
Scheduling. Reads the catalogue each sweep, decides which model should be
resident, and owns the policy for one that cannot be. A model added while
this process runs is picked up on the next sweep, and a failure it records
survives its own restart.

The worker has no knowledge of why a job was submitted -- whether it came
from a direct API call or a workflow step. It writes the result to
results_cache and publishes lifecycle events.
"""

import json
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import torch
from backend.messaging.base import NotificationBackend, QueueBackend
from dynawrap.backends.base import DBBackend
from pydantic import ValidationError

from models.catalogue import get_all_models
from shared.db_models import ModelCatalogueItem, set_model_config_env
from shared.enums import StatusCode
from shared.registry import _SPECS
from shared.results_cache import ResultsCache
from shared.schedule_models import EventType, LifecycleEvent, MarigoldMessage
from shared.usage import write_usage
from shared.usage_models import UsageItem
from tools.power_sampler import PowerSampler, check_model_vram, get_vram_state

logger = logging.getLogger(__name__)

_HEARTBEAT_BUFFER = 5  # seconds before timeout to extend visibility

IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "180"))


class ModelLoadError(Exception):
    """A model could not be made resident.

    Distinct from an error raised while a resident model is in use: the
    scheduler marks the catalogue row failed for this one and keeps
    sweeping for the other.
    """


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------


class LifecyclePublisher:
    """Publishes LifecycleEvents for one model. Never raises.

    Holds the fields every event for this model carries, so residency and
    drainage emit identical envelopes without sharing an object.
    """

    def __init__(
        self,
        notification_backend: NotificationBackend,
        topic: str,
        model_name: str,
        model_type: str,
        model_hash: str,
        worker_id: str,
        hostname: str,
    ):
        self.notification_backend = notification_backend
        self.topic = topic
        self.model_name = model_name
        self.model_hash = model_hash

        self._base_payload = {
            "model_name": model_name,
            "model_type": model_type,
            "model_hash": model_hash,
            "worker_id": worker_id,
            "hostname": hostname,
        }

    def publish(
        self, event_type: str, message_id: str = None, payload: dict = None
    ) -> None:
        event = LifecycleEvent(
            event_type=event_type,
            model_name=self.model_name,
            model_hash=self.model_hash,
            message_id=message_id,
            payload={**self._base_payload, **(payload or {})},
        )

        try:
            self.notification_backend.publish(self.topic, event.model_dump())
        except Exception as e:
            logger.warning("failed to publish %s: %s", event_type, e)


# ---------------------------------------------------------------------------
# Residency
# ---------------------------------------------------------------------------


@contextmanager
def resident_model(
    entry: ModelCatalogueItem, publisher: LifecyclePublisher
) -> Iterator[Any]:
    """Make entry's model resident for the duration of the block.

    Raises ModelLoadError if the model cannot be loaded or does not fit,
    having already released whatever was allocated. The VRAM check
    failing is an ordinary exit from this scope: the weights that landed
    before it ran are unloaded on the way out, which is what stops one
    oversized model from crowding out every model after it.
    """
    publisher.publish(EventType.MODEL_LOADING)

    if entry.type not in _SPECS:
        publisher.publish(
            EventType.MODEL_LOAD_FAILED, payload={"error": "unknown model_type"}
        )
        raise ModelLoadError(
            "unknown model_type '%s'; registered types: %s"
            % (entry.type, sorted(_SPECS))
        )

    spec = _SPECS[entry.type]
    logger.info(
        "loading '%s' (%s) via %s",
        entry.name, entry.type, spec.handler_class.__name__,
    )

    model = None

    try:
        try:
            model = spec.handler_class(entry.name)
            publisher.publish(EventType.MODEL_LOADED, payload=get_vram_state())

            if torch.cuda.is_available():
                check_model_vram(entry.name, model)
        except Exception as e:
            publisher.publish(EventType.MODEL_LOAD_FAILED, payload={"error": str(e)})
            raise ModelLoadError(str(e)) from e

        yield model

    finally:
        if model is not None:
            model.unload()


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def _heartbeat(
    queue_backend: QueueBackend,
    queue: str,
    receipt_handle: str,
    visibility_timeout: int,
    stop: threading.Event,
) -> None:
    """Extend queue visibility timeout periodically until stop is set."""
    interval = max(1, visibility_timeout - _HEARTBEAT_BUFFER)

    while not stop.wait(timeout=interval):
        try:
            queue_backend.extend_visibility(queue, receipt_handle, visibility_timeout)
            logger.debug("visibility timeout extended")
        except Exception as e:
            logger.warning("failed to extend visibility timeout: %s", e)


# ---------------------------------------------------------------------------
# Drainage
# ---------------------------------------------------------------------------


class QueueRunner:
    """Drain one queue using a model that is already resident.

    Polls until idle_timeout seconds have elapsed since the last message,
    then returns. idle_timeout=-1 polls indefinitely.

    The model is borrowed. Loading and unloading belong to resident_model,
    so an exception escaping run() leaves the caller's context manager to
    release it.

    Args:
        model:                A loaded model handler.
        entry:                Catalogue row for that model.
        queue_backend:        QueueBackend implementation.
        publisher:            LifecyclePublisher for this model.
        results_cache:        ResultsCache for direct result writes.
        power_sampler:        Shared PowerSampler, owned by the caller.
        visibility_timeout:   Seconds to hide a dequeued message.
        worker_id:            Stable identity of this process.
        hostname:             Host this process runs on.
        idle_timeout:         Seconds to keep polling after the queue
                              empties. -1 means poll indefinitely.
    """

    def __init__(
        self,
        model: Any,
        entry: ModelCatalogueItem,
        queue_backend: QueueBackend,
        publisher: LifecyclePublisher,
        results_cache: ResultsCache,
        power_sampler: PowerSampler,
        visibility_timeout: int,
        worker_id: str,
        hostname: str,
        idle_timeout: int = None,
    ):
        self.model = model
        self.queue = entry.queue_name
        self.model_name = entry.name
        self.model_type = entry.type
        self.queue_backend = queue_backend
        self.publisher = publisher
        self.results_cache = results_cache
        self.power_sampler = power_sampler
        self.visibility_timeout = visibility_timeout
        self.worker_id = worker_id
        self.hostname = hostname
        self.idle_timeout = idle_timeout if idle_timeout is not None else IDLE_TIMEOUT

        logger.info(
            "runner ready: version='%s' queue='%s' model='%s' idle_timeout=%is",
            os.getenv("BUILD_VERSION", "unknown"),
            self.queue,
            self.model_name,
            self.idle_timeout,
        )

    # -----------------------------------------------------------------------
    # Heartbeat
    # -----------------------------------------------------------------------

    @contextmanager
    def _heartbeat_context(self, receipt_handle: str):
        stop = threading.Event()
        thread = threading.Thread(
            target=_heartbeat,
            args=(
                self.queue_backend,
                self.queue,
                receipt_handle,
                self.visibility_timeout,
                stop,
            ),
            daemon=True,
        )
        thread.start()

        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=2)

    # -----------------------------------------------------------------------
    # Message handling
    # -----------------------------------------------------------------------

    def _get_message(self) -> tuple[MarigoldMessage | None, str | None]:
        """Dequeue one message and parse it as a MarigoldMessage.

        Malformed messages are deleted immediately and (None, None)
        returned.
        """
        payload, receipt_handle = self.queue_backend.receive(
            self.queue, self.visibility_timeout
        )

        if payload is None:
            return None, None

        try:
            msg = MarigoldMessage.model_validate(payload)
        except ValidationError as e:
            logger.error("malformed message, discarding: %s", e)
            self.queue_backend.delete(self.queue, receipt_handle)
            return None, None

        logger.info("[%s/%s] dequeued", msg.user_id, msg.message_id)
        self.publisher.publish(
            EventType.REQUEST_DEQUEUED,
            message_id=msg.message_id,
            payload={"user_id": msg.user_id},
        )

        return msg, receipt_handle

    def _report_error(self, msg: MarigoldMessage, error: str) -> None:
        """Write an error result and publish the matching event."""
        self.results_cache.write_error(
            msg.user_id, msg.message_id, error, StatusCode.INFERENCE_FAILED
        )
        self.publisher.publish(
            EventType.REQUEST_ERROR,
            message_id=msg.message_id,
            payload={"user_id": msg.user_id, "error": error},
        )

    def _process_message(self, msg: MarigoldMessage) -> None:
        """Run inference for one message and write results.

        Routing errors, validation failures and inference exceptions are
        all caught and reported as REQUEST_ERROR. The message is always
        deleted by the caller after this method returns.
        """
        self.publisher.publish(
            EventType.REQUEST_PROCESSING,
            message_id=msg.message_id,
            payload={"user_id": msg.user_id},
        )

        if msg.model_type != self.model_type:
            logger.critical(
                "[%s/%s] routing error: expected model_type '%s', got '%s'",
                msg.user_id, msg.message_id, self.model_type, msg.model_type,
            )
            self.publisher.publish(
                EventType.REQUEST_ERROR,
                message_id=msg.message_id,
                payload={
                    "user_id": msg.user_id,
                    "error": "model_type_mismatch",
                    "expected": self.model_type,
                    "got": msg.model_type,
                },
            )
            return

        try:
            spec = _SPECS[msg.model_type]
            request = spec.request_model.model_validate(
                {**msg.model_inputs, "model": msg.model_name}
            )

            logger.info(
                "[%s/%s] processing %s",
                msg.user_id, msg.message_id, json.dumps(request.model_dump()),
            )

            with self.power_sampler.sample() as sampler:
                result = self.model.process(msg.user_id, msg.message_id, request)

            usage_update = sampler.as_usage_fields()
            # FIXME: we need to capture this in power sampler
            # usage_update["cpu_offload_bytes"] = self._cpu_offload_bytes
            usage_update["worker_id"] = self.worker_id
            usage_update["hostname"] = self.hostname
            usage_update["application_id"] = msg.model_inputs.get("application_id") or ""

            result = result.model_copy(
                update={"usage": result.usage.model_copy(update=usage_update)}
            )

            write_usage(
                UsageItem.from_model_stats(
                    stats=result.usage,
                    user_id=msg.user_id,
                    model_type=self.model_type,
                    model_name=self.model_name,
                )
            )

            self.results_cache.write_result(
                msg.user_id, msg.message_id, result.model_dump()
            )

            self.publisher.publish(
                EventType.REQUEST_COMPLETE,
                message_id=msg.message_id,
                payload={"user_id": msg.user_id},
            )
            logger.info("[%s/%s] complete", msg.user_id, msg.message_id)

        except ValidationError as e:
            logger.exception(
                "[%s/%s] malformed request: %s", msg.user_id, msg.message_id, e
            )
            self._report_error(msg, str(e))

        except Exception as e:
            logger.exception(
                "[%s/%s] inference failed: %s", msg.user_id, msg.message_id, e
            )
            self._report_error(msg, str(e))

    # -----------------------------------------------------------------------
    # Run loop
    # -----------------------------------------------------------------------

    def run(self) -> None:
        """Poll the queue and process messages until idle_timeout elapses."""
        self.publisher.publish(EventType.WORKER_STARTED)
        last_message_at = time.monotonic()

        while True:
            msg, receipt_handle = self._get_message()

            if msg is None:
                idle_s = time.monotonic() - last_message_at

                if self.idle_timeout >= 0 and (
                    self.idle_timeout == 0 or idle_s >= self.idle_timeout
                ):
                    logger.info("idle for %.0fs, exiting", idle_s)
                    self.publisher.publish(EventType.WORKER_EXITING)
                    break

                self.publisher.publish(EventType.WORKER_IDLE)
                continue

            try:
                with self._heartbeat_context(receipt_handle):
                    self._process_message(msg)
            except Exception as e:
                logger.exception("unhandled error processing message: %s", e)
            finally:
                self.queue_backend.delete(self.queue, receipt_handle)

            last_message_at = time.monotonic()


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


class ModelScheduler:
    """Decide which model is resident, and handle the ones that cannot be.

    Each sweep reads the catalogue, creates any queue it has not created
    before, drains the queues of models an earlier sweep marked failed,
    then makes the deepest non-empty queue's model resident and hands it
    to a QueueRunner.

    The catalogue is read rather than injected, so a model added while
    this process runs is picked up on the next sweep and a failure this
    process records survives its own restart.

    Args:
        catalogue_backend:    DBBackend holding the model catalogue.
        catalogue_table:      Catalogue table name.
        queue_backend:        Shared QueueBackend instance.
        notification_backend: Shared NotificationBackend instance.
        visibility_timeout:   Passed to each QueueRunner.
        topic:                Notification topic name.
        results_cache:        ResultsCache for direct result writes.
        idle_timeout:         Passed to each QueueRunner. Default 0 so the
                              runner returns on an empty queue and the
                              next model can be loaded promptly.
        sweep_interval:       Seconds to sleep when every queue is empty.
        worker_id:            Overrides MARIGOLD_WORKER_ID and hostname.
    """

    def __init__(
        self,
        catalogue_backend: DBBackend,
        catalogue_table: str,
        queue_backend: QueueBackend,
        notification_backend: NotificationBackend,
        visibility_timeout: int,
        topic: str,
        results_cache: ResultsCache,
        idle_timeout: int = 0,
        sweep_interval: int = 10,
        worker_id: str = None,
    ):
        self.catalogue_backend = catalogue_backend
        self.catalogue_table = catalogue_table
        self.queue_backend = queue_backend
        self.notification_backend = notification_backend
        self.visibility_timeout = visibility_timeout
        self.topic = topic
        self.results_cache = results_cache
        self.idle_timeout = idle_timeout
        self.sweep_interval = sweep_interval

        self.hostname = socket.gethostname()
        self.worker_id = (
            worker_id or os.getenv("MARIGOLD_WORKER_ID") or self.hostname
        )

        self._known_queues: set[str] = set()
        self._power_sampler = PowerSampler()

        if self.results_cache is None:
            raise NotImplementedError("results_cache is now always required")

        logger.info("[%s] scheduler started on %s", self.worker_id, self.hostname)

    # -----------------------------------------------------------------------
    # Catalogue
    # -----------------------------------------------------------------------

    def _catalogue(self) -> list[ModelCatalogueItem]:
        """Read the catalogue fresh, failed entries included."""
        return get_all_models(self.catalogue_backend, self.catalogue_table)

    def _publisher_for(self, entry: ModelCatalogueItem) -> LifecyclePublisher:
        return LifecyclePublisher(
            notification_backend=self.notification_backend,
            topic=self.topic,
            model_name=entry.name,
            model_type=entry.type,
            model_hash=entry.hash,
            worker_id=self.worker_id,
            hostname=self.hostname,
        )

    def _ensure_queues(self, catalogue: list[ModelCatalogueItem]) -> None:
        """Create the queue for any entry this process has not seen.

        Queue creation belongs to whatever writes the catalogue row. This
        is repair: it makes the invariant true again for a row that
        arrived by another route, at one statement per queue per process.
        """
        for entry in catalogue:
            if entry.queue_name in self._known_queues:
                continue

            self.queue_backend.create_queue(entry.queue_name)
            self._known_queues.add(entry.queue_name)

    def _mark_failed(self, entry: ModelCatalogueItem, reason: str) -> None:
        """Record a load failure against the catalogue row.

        The API reads this to reject further submissions with 409, and the
        next sweep reads it to drain anything queued in the meantime.
        """
        self.catalogue_backend.save(
            self.catalogue_table,
            entry.model_copy(update={"failed_reason": reason}),
        )
        logger.warning("marked '%s/%s' failed: %s", entry.type.value, entry.name, reason)

    # -----------------------------------------------------------------------
    # Draining a queue whose model cannot load
    # -----------------------------------------------------------------------

    def _fail_queue(self, entry: ModelCatalogueItem, error: str) -> None:
        """Drain entry's queue, writing an error result for each message.

        Without this, whatever was queued before the load failed is never
        touched again: no error, no deletion, permanently invisible to
        the client that submitted it.
        """
        publisher = self._publisher_for(entry)
        drained = 0

        while True:
            payload, receipt_handle = self.queue_backend.receive(
                entry.queue_name, self.visibility_timeout
            )

            if payload is None:
                break

            try:
                msg = MarigoldMessage.model_validate(payload)
                self.results_cache.write_error(
                    msg.user_id, msg.message_id, error, StatusCode.MODEL_LOAD_FAILED
                )
                publisher.publish(
                    EventType.REQUEST_ERROR,
                    message_id=msg.message_id,
                    payload={"user_id": msg.user_id, "error": error},
                )
            except Exception:
                logger.exception(
                    "failed to write error result while draining '%s'", entry.queue_name
                )
            finally:
                self.queue_backend.delete(entry.queue_name, receipt_handle)

            drained += 1

        if drained:
            logger.warning(
                "drained and failed %d message(s) from '%s' after load failure",
                drained, entry.queue_name,
            )

    # -----------------------------------------------------------------------
    # Selection
    # -----------------------------------------------------------------------

    def _pick_entry(
        self, entries: list[ModelCatalogueItem]
    ) -> ModelCatalogueItem | None:
        """Return the entry with the deepest queue, or None if all empty."""
        if not entries:
            return None

        depths = [(m, self.queue_backend.depth(m.queue_name)) for m in entries]
        best_entry, best_depth = max(depths, key=lambda t: t[1])

        return best_entry if best_depth > 0 else None

    # -----------------------------------------------------------------------
    # Run loop
    # -----------------------------------------------------------------------

    def run(self) -> None:
        """Sweep queues, load, drain, unload, repeat indefinitely."""
        logger.info("ModelScheduler starting")

        serving: set[str] = set()

        try:
            while True:
                catalogue = self._catalogue()
                self._ensure_queues(catalogue)

                healthy = [m for m in catalogue if m.failed_reason is None]
                failed = [m for m in catalogue if m.failed_reason is not None]

                current = {m.hash for m in healthy}
                if current != serving:
                    logger.info(
                        "serving %d model(s): %s",
                        len(healthy), sorted(m.name for m in healthy),
                    )
                    serving = current

                for entry in failed:
                    if self.queue_backend.depth(entry.queue_name) > 0:
                        self._fail_queue(entry, entry.failed_reason)

                entry = self._pick_entry(healthy)

                if entry is None:
                    logger.debug("all queues empty, sleeping")
                    time.sleep(self.sweep_interval)
                    continue

                logger.info(
                    "selected model '%s' (%s) from queue '%s'",
                    entry.name, entry.type, entry.queue_name,
                )

                set_model_config_env(entry)
                publisher = self._publisher_for(entry)

                try:
                    with resident_model(entry, publisher) as model:
                        QueueRunner(
                            model=model,
                            entry=entry,
                            queue_backend=self.queue_backend,
                            publisher=publisher,
                            results_cache=self.results_cache,
                            power_sampler=self._power_sampler,
                            visibility_timeout=self.visibility_timeout,
                            worker_id=self.worker_id,
                            hostname=self.hostname,
                            idle_timeout=self.idle_timeout,
                        ).run()

                except ModelLoadError as e:
                    logger.exception("failed to load '%s': %s", entry.name, e)
                    self._fail_queue(entry, str(e))
                    self._mark_failed(entry, str(e))

                except Exception as e:
                    # A resident model that dies mid-drain says nothing
                    # about the model: the queue backend going away would
                    # do this to every model in turn, and marking each one
                    # failed would disable the catalogue over a few sweeps.
                    logger.exception("runner for '%s' died: %s", entry.name, e)

        finally:
            self._power_sampler.shutdown()
