"""Per-user, in-process rate limiter for cost control on LLM endpoints.

A sliding 1-hour window keyed by user id. In-memory → per-process; for multi-worker/horizontal
deployments swap the backing store for Redis behind this same interface.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.errors import RateLimitError

_WINDOW_SECONDS = 3600.0


class RateLimiter:
    def __init__(self, max_per_hour: int) -> None:
        self._max = max_per_hour
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, user_id: str) -> None:
        """Record a hit for [user_id]; raise [RateLimitError] if over the hourly quota."""
        now = time.monotonic()
        window = self._hits[user_id]
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if len(window) >= self._max:
            raise RateLimitError("Coaching request limit reached. Please try again later.")
        window.append(now)
