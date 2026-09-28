"""Bound the average inference rate without dropping slightly early frames."""

class FrameRateLimiter:
    def __init__(self, fps: float):
        self.fps = max(1.0, float(fps))
        # A quarter-frame allowance absorbs arrival jitter, not video frames.
        self.tokens = 1.25
        self.last_at = None

    def allow(self, now: float) -> bool:
        if self.last_at is not None:
            self.tokens = min(1.25, self.tokens + max(0.0, now - self.last_at) * self.fps)
        self.last_at = now
        if self.tokens < 1.0 - 1e-9:
            return False
        self.tokens = max(0.0, self.tokens - 1.0)
        return True
