"""Small process-local guardrails for expensive knowledge operations.

The limits are deliberately configurable and keyed by authenticated user. A
deployment with a shared gateway can replace this guard with a distributed
rate limiter without changing the knowledge API contract.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque


class QuotaExceeded(RuntimeError):
    """Raised when a caller exceeds an operation quota."""

    def __init__(self, operation: str, retry_after: int) -> None:
        super().__init__(f"{operation} quota exceeded; retry after {retry_after}s")
        self.operation = operation
        self.retry_after = retry_after


class KnowledgeQuota:
    def __init__(self) -> None:
        self.search_limit = max(1, int(os.getenv("CI_AGENT_RAG_SEARCH_RATE_LIMIT", "600")))
        self.evaluation_limit = max(1, int(os.getenv("CI_AGENT_RAG_EVALUATION_RATE_LIMIT", "30")))
        self.window_seconds = 60.0
        self._lock = threading.RLock()
        self._events: dict[str, dict[str, deque[float]]] = defaultdict(lambda: defaultdict(deque))

    def check(self, user_id: str, operation: str) -> None:
        limit = self.search_limit if operation == "search" else self.evaluation_limit
        now = time.monotonic()
        key = str(user_id or "default")
        with self._lock:
            bucket = self._events[key][operation]
            while bucket and now - bucket[0] >= self.window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
                raise QuotaExceeded(operation, retry_after)
            bucket.append(now)

    def status(self, user_id: str) -> dict[str, int | float]:
        now = time.monotonic()
        with self._lock:
            result: dict[str, int | float] = {
                "window_seconds": int(self.window_seconds),
                "search_limit": self.search_limit,
                "evaluation_limit": self.evaluation_limit,
            }
            for operation in ("search", "evaluation"):
                bucket = self._events[str(user_id or "default")][operation]
                while bucket and now - bucket[0] >= self.window_seconds:
                    bucket.popleft()
                result[f"{operation}_used"] = len(bucket)
            return result


quota = KnowledgeQuota()

