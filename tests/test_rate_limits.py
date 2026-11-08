from concurrent.futures import ThreadPoolExecutor

import pytest

from services.playback_service import APIError
from services.rate_limit_service import RateLimitService


@pytest.mark.parametrize("kind,burst,seconds", [("request", 10, 1), ("command", 2, 2),
                                               ("failure", 30, 60), ("proxy", 300, 60)])
def test_exact_burst_boundary(kind, burst, seconds):
    now = [0]
    limiter = RateLimitService(clock=lambda: now[0])
    for _ in range(burst):
        limiter.consume(kind, "one")
    with pytest.raises(APIError) as error:
        limiter.consume(kind, "one")
    assert error.value.status == 429 and error.value.retry_after == seconds
    limiter.consume(kind, "two")
    now[0] = seconds
    limiter.consume(kind, "one")


@pytest.mark.parametrize("kind,count,step", [("command", 10, 3), ("request", 120, 0.49)])
def test_minute_window(kind, count, step):
    now = [0]
    limiter = RateLimitService(clock=lambda: now[0])
    for _ in range(count):
        limiter.consume(kind, "one")
        now[0] += step
    if now[0] < 60:
        with pytest.raises(APIError):
            limiter.consume(kind, "one")
    else:
        limiter.consume(kind, "one")
    now[0] = 120
    limiter.consume(kind, "one")


def test_bucket_cap_fails_closed_then_idle_expiry_releases_capacity():
    now = [0]
    limiter = RateLimitService(clock=lambda: now[0], max_buckets=2)
    limiter.consume("request", "one")
    limiter.consume("request", "two")
    with pytest.raises(APIError):
        limiter.consume("request", "three")
    assert len(limiter._buckets) == 2
    now[0] = 900
    limiter.consume("request", "three")
    assert len(limiter._buckets) == 1


def test_concurrent_consumers_cannot_exceed_burst():
    limiter = RateLimitService(clock=lambda: 0)
    def attempt(_):
        try:
            limiter.consume("command", "one")
            return 1
        except APIError:
            return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(40))) == 2
