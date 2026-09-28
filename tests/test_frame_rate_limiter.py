from backend.frame_rate_limiter import FrameRateLimiter


def test_jitter_rate_and_no_catchup_burst():
    limiter = FrameRateLimiter(5)
    times = [i / 5 + (0.015 if i % 2 else 0) for i in range(100)]
    assert all(limiter.allow(t) for t in times)
    limiter = FrameRateLimiter(5)
    assert 49 <= sum(limiter.allow(i / 25) for i in range(250)) <= 51
    assert limiter.allow(100)
    assert not any(limiter.allow(100) for _ in range(20))
