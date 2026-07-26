import logging
import os
import threading
import time

from fastapi import HTTPException

logger = logging.getLogger("wpai.ratelimit")


class FixedWindowLimiter:
    """Minimal in-memory fixed-window rate limiter.

    NOTE: counters live in this process only — with multiple uvicorn/gunicorn workers each
    worker keeps its own window, so the effective limit is `limit * workers`. Set REDIS_URL
    to get the Redis-backed limiter below, which shares one window across all workers. This
    in-memory version is the fallback (single-process backend / dev / tests).
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int | None = None) -> None:
        """Count one hit for `key`; raise HTTP 429 once the window limit is exceeded.
        `limit` overrides the instance default — e.g. a per-plan limit instead of the
        global one — without needing a separate limiter instance per plan."""
        limit = self.limit if limit is None else limit
        now = time.time()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            if count > limit:
                retry_after = max(int(self.window - (now - start)), 1)
                raise HTTPException(
                    429, "rate limit exceeded", headers={"Retry-After": str(retry_after)}
                )


class RedisFixedWindowLimiter:
    """Fixed-window limiter backed by Redis so every app worker shares one window.

    The window is anchored at the first hit (an atomic INCR that also sets EXPIRE), matching
    the in-memory limiter's semantics; the key expires after `window` seconds and the count
    resets on the next hit.

    A rate limiter is a cost/abuse guard, not a security boundary, so this FAILS OPEN: if
    Redis is unreachable the request is allowed (and logged), never turned into a 500. The
    tradeoff is unlimited traffic during a Redis outage, which is preferable to taking chat
    down with it.
    """

    # INCR the counter; on the first hit of a fresh window, set its TTL. Atomic (one script).
    _SCRIPT = (
        "local current = redis.call('INCR', KEYS[1])\n"
        "if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end\n"
        "return current"
    )

    def __init__(self, limit: int, window_seconds: int, redis_client):
        self.limit = limit
        self.window = window_seconds
        self._redis = redis_client
        self._script = redis_client.register_script(self._SCRIPT)

    def check(self, key: str, limit: int | None = None) -> None:
        limit = self.limit if limit is None else limit
        rkey = f"rl:{key}:{self.window}"
        try:
            count = int(self._script(keys=[rkey], args=[self.window]))
        except Exception as exc:  # noqa: BLE001 — fail open: a Redis outage must not 500 the request
            logger.warning("ratelimit.redis_unavailable key=%s error=%s", key, exc)
            return
        if count > limit:
            try:
                ttl = self._redis.ttl(rkey)
            except Exception:  # noqa: BLE001
                ttl = self.window
            retry_after = max(int(ttl), 1)
            raise HTTPException(
                429, "rate limit exceeded", headers={"Retry-After": str(retry_after)}
            )


def make_limiter(limit: int, window_seconds: int):
    """Build the right limiter for the environment: Redis-backed (shared across workers) when
    REDIS_URL is set and reachable, otherwise the in-memory fallback. A bad/unreachable
    REDIS_URL at startup logs a warning and falls back rather than crashing the app."""
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return FixedWindowLimiter(limit, window_seconds)
    try:
        import redis  # imported lazily so the dep is only needed when REDIS_URL is set

        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        logger.info("ratelimit.redis_enabled")
        return RedisFixedWindowLimiter(limit, window_seconds, client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ratelimit.redis_init_failed error=%s (falling back to in-memory)", exc)
        return FixedWindowLimiter(limit, window_seconds)
