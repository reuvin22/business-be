import time


def current_time_ms() -> int:
    """Milliseconds since 1970, the same as Date.now() in JavaScript."""
    return int(time.time() * 1000)
