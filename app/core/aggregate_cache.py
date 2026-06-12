"""Small process-local TTL cache for expensive read-only aggregates."""

from copy import deepcopy
import threading
import time


_CACHE = {}
_LOCK = threading.Lock()
_MAX_ENTRIES = 64


def cached_aggregate(key, ttl_seconds, loader):
    """
    Return a defensive copy of a cached aggregate or compute it once.

    This cache is intentionally process-local: it avoids repeated expensive
    read-only queries during page refreshes without adding database writes or
    affecting live/session state.
    """
    now = time.monotonic()

    with _LOCK:
        entry = _CACHE.get(str(key))
        if entry and entry["expires_at"] > now:
            return deepcopy(entry["value"])

    value = loader()

    with _LOCK:
        if len(_CACHE) >= _MAX_ENTRIES:
            expired = [cache_key for cache_key, item in _CACHE.items() if item["expires_at"] <= now]
            for cache_key in expired:
                _CACHE.pop(cache_key, None)

            if len(_CACHE) >= _MAX_ENTRIES:
                oldest = min(_CACHE, key=lambda cache_key: _CACHE[cache_key]["created_at"])
                _CACHE.pop(oldest, None)

        _CACHE[str(key)] = {
            "value": deepcopy(value),
            "created_at": now,
            "expires_at": now + max(1, int(ttl_seconds)),
        }

    return deepcopy(value)


def clear_aggregate_cache():
    with _LOCK:
        _CACHE.clear()


def cached_query_rows(db, key, ttl_seconds, sql, params=()):
    return cached_aggregate(
        key,
        ttl_seconds,
        lambda: [dict(row) for row in (db.query(sql, params) or [])],
    )
