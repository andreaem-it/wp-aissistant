import threading
import time

from fastapi import HTTPException


class FixedWindowLimiter:
    """Minimal in-memory fixed-window rate limiter.

    NOTE: counters live in this process only — with multiple uvicorn/gunicorn workers each
    worker keeps its own window, so the effective limit is `limit * workers`. For a real
    multi-worker deployment back this with a shared store (Redis via `limits`/`slowapi`).
    Good enough as a first abuse/cost guard for a single-process backend.
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Count one hit for `key`; raise HTTP 429 once the window limit is exceeded."""
        now = time.time()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            if count > self.limit:
                retry_after = max(int(self.window - (now - start)), 1)
                raise HTTPException(
                    429, "rate limit exceeded", headers={"Retry-After": str(retry_after)}
                )
