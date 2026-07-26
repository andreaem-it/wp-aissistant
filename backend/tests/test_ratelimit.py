import pytest
from fastapi import HTTPException

from app.ratelimit import FixedWindowLimiter, RedisFixedWindowLimiter


def test_allows_up_to_limit():
    limiter = FixedWindowLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        limiter.check("k")  # should not raise


def test_blocks_over_limit_with_429():
    limiter = FixedWindowLimiter(limit=2, window_seconds=60)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(HTTPException) as excinfo:
        limiter.check("k")
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers.get("Retry-After")


def test_keys_are_independent():
    limiter = FixedWindowLimiter(limit=1, window_seconds=60)
    limiter.check("a")
    limiter.check("b")  # different key, must not raise


# ---- Redis-backed limiter (shared across workers). Uses fakeredis; skipped if absent. ----


def _fake_redis():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeStrictRedis()


def test_redis_allows_up_to_limit():
    limiter = RedisFixedWindowLimiter(limit=3, window_seconds=60, redis_client=_fake_redis())
    for _ in range(3):
        limiter.check("k")  # should not raise


def test_redis_blocks_over_limit_with_429():
    limiter = RedisFixedWindowLimiter(limit=2, window_seconds=60, redis_client=_fake_redis())
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(HTTPException) as excinfo:
        limiter.check("k")
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers.get("Retry-After")


def test_redis_keys_are_independent():
    limiter = RedisFixedWindowLimiter(limit=1, window_seconds=60, redis_client=_fake_redis())
    limiter.check("a")
    limiter.check("b")  # different key, must not raise


def test_redis_per_call_limit_override():
    limiter = RedisFixedWindowLimiter(limit=100, window_seconds=60, redis_client=_fake_redis())
    limiter.check("k", limit=1)
    with pytest.raises(HTTPException):
        limiter.check("k", limit=1)  # override wins over the instance default


def test_redis_fails_open_when_unavailable():
    """A Redis outage must allow the request, not 500 it."""
    class BrokenScript:
        def __call__(self, *a, **k):
            raise ConnectionError("redis down")

    class BrokenRedis:
        def register_script(self, _):
            return BrokenScript()

    limiter = RedisFixedWindowLimiter(limit=1, window_seconds=60, redis_client=BrokenRedis())
    limiter.check("k")
    limiter.check("k")  # would exceed the limit, but fail-open => no raise
