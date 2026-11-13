import random
import time
from collections.abc import Callable
from typing import TypeVar

from ytmusicapi.exceptions import YTMusicServerError

T = TypeVar("T")


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    val = getattr(resp, "status_code", None)
    return val if isinstance(val, int) else None


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, YTMusicServerError):
        return True
    code = _status_code(exc)
    return code == 429 or (code is not None and 500 <= code < 600)


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 5,
    base: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn with exponential backoff and jitter on 429/5xx/YTMusicServerError."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts - 1 or not _is_retryable(exc):
                raise
            delay = base * (2**attempt) + random.uniform(0, base * 0.5)
            sleep(delay)
    raise AssertionError("unreachable")
