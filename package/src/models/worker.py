"""Worker loop for Marigold model inference tasks.

Reads one message at a time from the configured queue backend, validates
the payload, runs inference, writes the result to the results table, and
deletes the message.

The worker has no knowledge of why a job was submitted -- whether it came
from a direct API call or a workflow step. It writes the result to
results_cache and publishes a REQUEST_COMPLETE lifecycle event. Downstream
consumers (state_listener on AWS, listener_logic locally) handle any
further routing.

QueueWorker
-----------
Single model, single queue. Loads the model on construction, polls until
idle_timeout seconds have elapsed since the last message, calls
model.unload(), then returns. idle_timeout=-1 polls indefinitely.

MultiQueueWorker
----------------
Multiple models, multiple queues. Polls all queue depths, loads the model
with the deepest non-empty queue, constructs a QueueWorker, drains it,
then sweeps again. Exits when all queues are empty on a full sweep.
"""

import json
import logging
import os
import threading
import time
from contextlib import contextmanager

import torch
from backend.messaging.base import NotificationBackend, QueueBackend
from pydantic import ValidationError
from shared.registry import _SPECS
from shared.sns_models import EventType, LifecycleEvent
from shared.sqs_models import MarigoldSQSMessage
from tools.polling.results_cache import ResultsCache
from tools.power_sampler import (ModelVRAMError, PowerSampler,
                                 check_model_vram, get_vram_state)
from shared.usage_models import UsageItem
from shared.usage import write_usage
from shared.db_models import ModelCatalogueItem, set_model_config_env

logger = logging.getLogger(__name__)

_HEARTBEAT_BUFFER = 5  # seconds before timeout to extend visibility

IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "180"))


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
# QueueWorker
# ---------------------------------------------------------------------------


class QueueWorker:
    """Backend-agnostic worker loop for a single model and queue.

    Loads the model on construction. Polls the queue until idle_timeout
    seconds have elapsed since the last message, then calls model.unload()
    and returns. idle_timeout=-1 polls indefinitely (local development).

    The worker writes results via results_cache when injected (local path)
    or via outputs.update_results_table() on AWS. It publishes lifecycle
    events for all state transitions. It has no knowledge of workflows --
    workflow step handling is the responsibility of the state machine.

    Args:
        queue:                Queue name or identifier.
        model_name:           HuggingFace model identifier.
        model_type:           ModelType value, for registry lookup.
        model_hash:           md5(model_name), for event payloads.
        queue_backend:        QueueBackend implementation.
        notification_backend: NotificationBackend implementation.
        visibility_timeout:   Seconds to hide a dequeued message.
        topic:                Notification topic name.
        idle_timeout:         Seconds to keep polling after queue empties.
                              -1 means poll indefinitely.
        results_cache:        Optional ResultsCache for direct result writes.
                              None on AWS -- falls back to
                              outputs.update_results_table().
    """

    def __init__(
        self,
        queue: str,
        model_name: str,
        model_type: str,
        model_hash: str,
        queue_backend: QueueBackend,
        notification_backend: NotificationBackend,
        visibility_timeout: int,
        topic: str,
        idle_timeout: int = None,
        results_cache: ResultsCache = None,
    ):
        self.queue = queue
        self.model_name = model_name
        self.model_type = model_type
        self.model_hash = model_hash
        self.queue_backend = queue_backend
        self.notification_backend = notification_backend
        self.visibility_timeout = visibility_timeout
        self.topic = topic
        self.idle_timeout = idle_timeout if idle_timeout is not None else IDLE_TIMEOUT
        self.results_cache = results_cache
        self._power_sampler = PowerSampler()

        self._base_payload = {
            "model_name": model_name,
            "model_type": model_type,
            "model_hash": model_hash,
        }

        self._publish(EventType.MODEL_LOADING)

        if model_type not in _SPECS:
            self._publish(
                EventType.MODEL_LOAD_FAILED, payload={"error": "unknown model_type"}
            )
            raise ValueError(
                "unknown model_type '%s'; registered types: %s"
                % (model_type, sorted(_SPECS))
            )

        spec = _SPECS[model_type]
        logger.info(
            "loading '%s' (%s) via %s",
            model_name,
            model_type,
            spec.handler_class.__name__,
        )

        try:
            self.model = spec.handler_class(model_name)
        except Exception as e:
            self._publish(EventType.MODEL_LOAD_FAILED, payload={"error": str(e)})
            raise

        self._publish(EventType.MODEL_LOADED, payload=get_vram_state())

        logger.info(
            "worker ready: version='%s' queue='%s' model='%s' idle_timeout=%is",
            os.getenv("BUILD_VERSION", "unknown"),
            self.queue,
            self.model_name,
            self.idle_timeout,
        )

        # validate the load is all in memory and throw if not
        if torch.cuda.is_available():
            # this will throw a modelvramerror
            check_model_vram(model_name, self.model)

    # ---------------------------------------------------------------------------
    # Notifications
    # ---------------------------------------------------------------------------

    def _publish(
        self, event_type: str, message_id: str = None, payload: dict = None
    ) -> None:
        """Publish a LifecycleEvent via the notification backend. Never raises."""
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
    # Result persistence
    # ---------------------------------------------------------------------------

    def _write_result(self, user_id: str, message_id: str, response: dict) -> None:
        """Write the inference result to the appropriate results backend.

        Local path (results_cache injected):
            Calls results_cache.write_result() which updates the existing
            queued row to status=complete with the result payload.

        AWS path (results_cache is None):
            Delegates to outputs.update_results_table() which writes to
            DynamoDB using the module-level client.
        """
        if self.results_cache is not None:
            self.results_cache.write_result(user_id, message_id, response)
        else:
            from shared.outputs import update_results_table

            update_results_table(user_id, message_id, response)

    def _write_error(self, user_id: str, message_id: str, error: str) -> None:
        """Write an error status to the results backend."""
        if self.results_cache is not None:
            self.results_cache.write_error(user_id, message_id, error)
        else:
            from shared.outputs import update_results_table

            update_results_table(user_id, message_id, {"error": error}, status="error")

    # ---------------------------------------------------------------------------
    # Heartbeat
    # ---------------------------------------------------------------------------

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

    # ---------------------------------------------------------------------------
    # Message handling
    # ---------------------------------------------------------------------------

    def _get_message(self) -> tuple[MarigoldSQSMessage | None, str | None]:
        """Dequeue one message and parse it as a MarigoldSQSMessage.

        Malformed messages are deleted immediately and (None, None) returned.
        """
        payload, receipt_handle = self.queue_backend.receive(
            self.queue, self.visibility_timeout
        )

        if payload is None:
            return None, None

        try:
            sqs_msg = MarigoldSQSMessage.model_validate(payload)
        except ValidationError as e:
            logger.error("malformed message, discarding: %s", e)
            self.queue_backend.delete(self.queue, receipt_handle)
            return None, None

        logger.info("[%s/%s] dequeued", sqs_msg.user_id, sqs_msg.message_id)
        self._publish(
            EventType.REQUEST_DEQUEUED,
            message_id=sqs_msg.message_id,
            payload={"user_id": sqs_msg.user_id},
        )
        return sqs_msg, receipt_handle

    def _process_message(self, sqs_msg: MarigoldSQSMessage) -> None:
        """Run inference for one message and write results.

        Routing errors, validation failures, and inference exceptions are
        all caught and reported as REQUEST_ERROR events. The message is
        always deleted by the caller after this method returns.
        """
        self._publish(
            EventType.REQUEST_PROCESSING,
            message_id=sqs_msg.message_id,
            payload={"user_id": sqs_msg.user_id},
        )

        if sqs_msg.model_type != self.model_type:
            logger.critical(
                "[%s/%s] routing error: expected model_type '%s', got '%s'",
                sqs_msg.user_id,
                sqs_msg.message_id,
                self.model_type,
                sqs_msg.model_type,
            )
            self._publish(
                EventType.REQUEST_ERROR,
                message_id=sqs_msg.message_id,
                payload={
                    "user_id": sqs_msg.user_id,
                    "error": "model_type_mismatch",
                    "expected": self.model_type,
                    "got": sqs_msg.model_type,
                },
            )
            return

        try:
            spec = _SPECS[sqs_msg.model_type]
            request = spec.request_model.model_validate(
                {**sqs_msg.model_inputs, "model": sqs_msg.model_name}
            )

            logger.info(
                "[%s/%s] processing %s",
                sqs_msg.user_id,
                sqs_msg.message_id,
                json.dumps(request.model_dump()),
            )

            # track power usage.
            with self._power_sampler.sample() as sampler:
                result = self.model.process(sqs_msg.user_id, sqs_msg.message_id, request)

            usage_update = sampler.as_usage_fields()
            # FIXME: we need to capture this is power sampler
            #usage_update["cpu_offload_bytes"] = self._cpu_offload_bytes
            result = result.model_copy(update={"usage": result.usage.model_copy(update=usage_update)})

            item = UsageItem.from_model_stats(
                stats=result.usage,
                user_id=sqs_msg.user_id,
                model_type=self.model_type,
                model_name=self.model_name,
            )
            write_usage(item)

            # update the results db
            self._write_result(sqs_msg.user_id, sqs_msg.message_id, result.model_dump())

            self._publish(EventType.REQUEST_COMPLETE, message_id=sqs_msg.message_id, payload={"user_id": sqs_msg.user_id})
            logger.info("[%s/%s] complete", sqs_msg.user_id, sqs_msg.message_id)

        except ValidationError as e:
            logger.exception(
                "[%s/%s] malformed request: %s", sqs_msg.user_id, sqs_msg.message_id, e
            )
            self._write_error(sqs_msg.user_id, sqs_msg.message_id, str(e))
            self._publish(
                EventType.REQUEST_ERROR,
                message_id=sqs_msg.message_id,
                payload={"user_id": sqs_msg.user_id, "error": str(e)},
            )

        except Exception as e:
            logger.exception(
                "[%s/%s] inference failed: %s", sqs_msg.user_id, sqs_msg.message_id, e
            )
            self._write_error(sqs_msg.user_id, sqs_msg.message_id, str(e))
            self._publish(
                EventType.REQUEST_ERROR,
                message_id=sqs_msg.message_id,
                payload={"user_id": sqs_msg.user_id, "error": str(e)},
            )

    # ---------------------------------------------------------------------------
    # Run loop
    # ---------------------------------------------------------------------------

    def run(self) -> None:
        """Poll the queue and process messages until idle_timeout elapses.

        idle_timeout=-1 polls indefinitely.
        Calls model.unload() before returning regardless of exit reason.
        """
        self._publish(EventType.WORKER_STARTED)
        last_message_at = time.monotonic()

        try:
            while True:
                sqs_msg, receipt_handle = self._get_message()

                if sqs_msg is None:
                    idle_s = time.monotonic() - last_message_at
                    if self.idle_timeout >= 0 and (
                        self.idle_timeout == 0 or idle_s >= self.idle_timeout
                    ):
                        logger.info("idle for %.0fs, exiting", idle_s)
                        self._publish(EventType.WORKER_EXITING)
                        break
                    self._publish(EventType.WORKER_IDLE)
                    continue

                try:
                    with self._heartbeat_context(receipt_handle):
                        self._process_message(sqs_msg)
                except Exception as e:
                    logger.exception("unhandled error processing message: %s", e)
                finally:
                    self.queue_backend.delete(self.queue, receipt_handle)

                last_message_at = time.monotonic()

        finally:
            self.model.unload()
            self._power_sampler.shutdown()


# ---------------------------------------------------------------------------
# MultiQueueWorker
# ---------------------------------------------------------------------------


class MultiQueueWorker:
    """Multi-queue worker for single-GPU local development.

    Polls all queue depths in a sweep, loads the model for the deepest
    non-empty queue, constructs a QueueWorker to drain it, then sweeps
    again. QueueWorker.run() calls model.unload() before returning.

    Sleeps between sweeps when all queues are empty, then checks again.

    Args:
        model_catalogue:        List of model catalogue items, each containing:
                                model_hash, queue_name, model_name, model_type
        queue_backend:        Shared QueueBackend instance.
        notification_backend: Shared NotificationBackend instance.
        visibility_timeout:   Passed to each QueueWorker.
        topic:                Notification topic name.
        idle_timeout:         Passed to each QueueWorker. Default 0 so the
                              worker exits immediately on empty queue and the
                              next model can be loaded promptly.
        results_cache:        Optional ResultsCache for direct result writes.
    """

    def __init__(
        self,
        model_catalogue: list[ModelCatalogueItem],
        queue_backend: QueueBackend,
        notification_backend: NotificationBackend,
        visibility_timeout: int,
        topic: str,
        idle_timeout: int = 0,
        results_cache: ResultsCache = None,
    ):
        self.model_catalogue = model_catalogue
        self.queue_backend = queue_backend
        self.notification_backend = notification_backend
        self.visibility_timeout = visibility_timeout
        self.topic = topic
        self.idle_timeout = idle_timeout
        self.results_cache = results_cache

    def _pick_entry(self) -> dict | None:
        """Return the entry with the highest queue depth, or None if all empty."""
        depths = [
            (m, self.queue_backend.depth(m.queue_name))
            for m in self.model_catalogue
        ]
        best_entry, best_depth = max(depths, key=lambda t: t[1])
        return best_entry if best_depth > 0 else None

    def run(self) -> None:
        """Sweep queues, load, drain, unload, repeat indefinitely."""
        logger.info("MultiQueueWorker starting: %d queues", len(self.model_catalogue))

        while True:
            entry = self._pick_entry()

            if entry is None:
                logger.info("all queues empty, sleeping")
                time.sleep(10)
                continue

            logger.info(
                "selected model '%s' (%s) from queue '%s'",
                entry.name,
                entry.type,
                entry.queue_name,
            )

            # insert the custom envvars into the runtime
            set_model_config_env(entry)

            try:
                worker = QueueWorker(
                    queue=entry.queue_name,
                    model_name=entry.name,
                    model_type=entry.type,
                    model_hash=entry.hash,
                    queue_backend=self.queue_backend,
                    notification_backend=self.notification_backend,
                    visibility_timeout=self.visibility_timeout,
                    topic=self.topic,
                    idle_timeout=self.idle_timeout,
                    results_cache=self.results_cache,
                )
            except ModelVRAMError as e:
                logger.exception("model '%s' failed VRAM check: %s", entry.name, e)
                # remove this model from this worker
                self.model_catalogue = [m for m in self.model_catalogue if m.hash != entry.hash]
                # FIXME: do we continue here, or just exit?
                continue
            except Exception as e:
                logger.exception("failed to load model '%s': %s -- skipping", entry.name, e)
                self.model_catalogue = [m for m in self.model_catalogue if m.hash != entry.hash]
                continue

            worker.run()
