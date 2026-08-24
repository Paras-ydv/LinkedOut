"""A deliberately tiny in-process TTL cache.

Phase 3's stats/layoff-timeline endpoints are computed-on-read (query +
SQL-aggregate at request time, no background recompute job — see
app/services/stats.py) because the dataset is small enough right now that
computed-on-read avoids stale-cache bugs entirely. This cache sits in
front of that computation anyway, not because it's needed at this scale,
but to establish the caching pattern before Phase 5 hardening.

Deliberately NOT a distributed cache (no Redis) and NOT thread-safe
beyond what the GIL + a single dict assignment already gives you — good
enough for a single async process. A multi-worker deployment would see
each worker with its own cache (i.e. an effective cache-hit rate lower
than the TTL implies), which is fine: correctness never depends on a hit,
only on the TTL being short enough that staleness doesn't matter.
"""

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float):
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            del self._entries[key]
            return None
        return entry.value

    def set(self, key: str, value: T) -> None:
        self._entries[key] = _Entry(value=value, expires_at=time.monotonic() + self._ttl_seconds)

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
