import pytest
from fastapi import HTTPException

from app.ratelimit import FixedWindowLimiter


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
