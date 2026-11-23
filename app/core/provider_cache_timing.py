"""Request-scoped totals for provider HTTP calls and aggregate caches."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class ProviderCacheTiming:
    provider_ns: int = 0
    provider_calls: int = 0
    cache_ns: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)


provider_cache_timing = ContextVar("provider_cache_timing", default=None)
