from __future__ import annotations

import time
from collections import defaultdict


class SlidingWindowLimiter:
    def __init__(self, limit: int = 30, window_seconds: float = 60.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        recent = [stamp for stamp in self._hits[key] if now - stamp < self.window_seconds]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        return True

    def reset(self) -> None:
        self._hits.clear()


public_verify_limiter = SlidingWindowLimiter(limit=30, window_seconds=60.0)
