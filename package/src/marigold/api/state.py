# for local inference, mainly

_state: dict = {}


def configure(
    models_config: dict,
    queue_backend,
    notification_backend,
    results_cache,
    topic: str,
) -> None:
    _state.update(
        models_config=models_config,
        queue_backend=queue_backend,
        notification_backend=notification_backend,
        results_cache=results_cache,
        topic=topic,
    )


def get_receiver_state() -> dict:
    return _state
