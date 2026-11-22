"""Small process-local TTL cache for expensive read-only aggregates."""

from copy import deepcopy
import threading
import time

from core.provider_cache_timing import provider_cache_timing


_CACHE = {}
_LOCK = threading.Lock()
_IN_FLIGHT = {}
_MAX_ENTRIES = 64


def cached_aggregate(key, ttl_seconds, loader):
    """
    Return a defensive copy of a cached aggregate or compute it once.

    This cache is intentionally process-local: it avoids repeated expensive
    read-only queries during page refreshes without adding database writes or
    affecting live/session state.
    """
    timing = provider_cache_timing.get()
    if timing is None:
        return _cached_aggregate(key, ttl_seconds, loader, timing)
    started_at = time.perf_counter_ns()
    try:
        return _cached_aggregate(key, ttl_seconds, loader, timing)
    finally:
        duration_ns = time.perf_counter_ns() - started_at
        with timing.lock:
            timing.cache_ns += duration_ns


def _cached_aggregate(key, ttl_seconds, loader, timing):
    key = str(key)
    ttl = max(1, int(ttl_seconds))
    while True:
        with _LOCK:
            entry = _CACHE.get(key)
            if entry and entry["expires_at"] > time.monotonic():
                if timing is not None:
                    timing.cache_hits += 1
                value = entry["value"]
                hit = True
            else:
                hit = False
                pending = _IN_FLIGHT.get(key)
                if pending is None:
                    pending = threading.Event()
                    _IN_FLIGHT[key] = pending
                    if timing is not None:
                        timing.cache_misses += 1
                    break
        if hit:
            # Published values are never mutated. Copy outside the global lock
            # so a large report cannot stall cache reads for unrelated pages.
            return deepcopy(value)
        # Share work for this key without blocking unrelated aggregates.
        pending.wait()

    try:
        value = loader()
        stored_value = deepcopy(value)
    except BaseException:
        with _LOCK:
            _IN_FLIGHT.pop(key, None)
            pending.set()
        raise

    with _LOCK:
        now = time.monotonic()
        if len(_CACHE) >= _MAX_ENTRIES:
            expired = [cache_key for cache_key, item in _CACHE.items() if item["expires_at"] <= now]
            for cache_key in expired:
                _CACHE.pop(cache_key, None)

            if len(_CACHE) >= _MAX_ENTRIES:
                oldest = min(_CACHE, key=lambda cache_key: _CACHE[cache_key]["created_at"])
                _CACHE.pop(oldest, None)

        _CACHE[key] = {
            "value": stored_value,
            "created_at": now,
            "expires_at": now + ttl,
        }
        _IN_FLIGHT.pop(key, None)
        pending.set()

    return deepcopy(value)


def clear_aggregate_cache():
    with _LOCK:
        _CACHE.clear()


def peek_aggregate(key):
    """Reuse an existing snapshot for decoration without invoking a loader."""
    with _LOCK:
        entry = _CACHE.get(str(key))
        value = entry['value'] if entry else None
    return deepcopy(value)


def cached_query_rows(db, key, ttl_seconds, sql, params=()):
    return cached_aggregate(
        key,
        ttl_seconds,
        lambda: [dict(row) for row in (db.query(sql, params) or [])],
    )
