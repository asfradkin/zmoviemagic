"""Process-local, bounded sliding windows. One Gunicorn worker is required."""
from collections import deque
import math
from threading import Lock
import time

from services.playback_service import APIError


class RateLimitService:
    POLICIES = {
        "request": ((120, 60), (10, 1)),
        "command": ((10, 60), (2, 2)),
        "failure": ((30, 60),),
        "proxy": ((300, 60),),
    }

    def __init__(self, clock=time.monotonic, max_buckets=1024, idle_seconds=900):
        if not 1 <= max_buckets <= 1024 or not 60 <= idle_seconds <= 900:
            raise ValueError("Invalid limiter bounds")
        self.clock, self.max_buckets, self.idle_seconds = clock, max_buckets, idle_seconds
        self._buckets = {}
        self._lock = Lock()

    def consume(self, kind, principal):
        policies = self.POLICIES[kind]
        now = self.clock()
        key = (kind, principal)
        with self._lock:
            self._buckets = {key: bucket for key, bucket in self._buckets.items()
                             if now - bucket[1] < self.idle_seconds}
            if key not in self._buckets:
                if len(self._buckets) >= self.max_buckets:
                    self._deny(60)
                self._buckets[key] = (deque(), now)
            events, _ = self._buckets[key]
            self._buckets[key] = (events, now)
            while events and events[0] <= now - 60:
                events.popleft()
            waits = []
            for limit, seconds in policies:
                recent = [stamp for stamp in events if stamp > now - seconds]
                if len(recent) >= limit:
                    waits.append(recent[-limit] + seconds - now)
            if waits:
                self._deny(max(1, math.ceil(max(waits))))
            events.append(now)

    @staticmethod
    def _deny(seconds):
        raise APIError("rate_limited", 429, "Too many requests. Please wait.", seconds)
