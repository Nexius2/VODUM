"""Bounded grace period for probable playback device switches."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


STREAM_SWITCH_GRACE_SECONDS = 300
_CACHE_RETENTION_SECONDS = 3600
_LOCK = threading.RLock()
_FIRST_SEEN: dict[str, float] = {}


def _clean(value) -> str:
    return str(value or "").strip().lower()


def _playback_identity(session: dict) -> str:
    media_type = _clean(session.get("media_type"))
    series = _clean(session.get("grandparent_title"))
    season = _clean(session.get("parent_title"))
    title = _clean(session.get("title"))

    if media_type in {"episode", "series", "show"} and series and title:
        return f"episode:{series}:{season}:{title}"
    if media_type in {"movie", "film"} and title:
        return f"movie:{title}"

    media_key = _clean(session.get("media_key"))
    if media_key:
        return f"key:{media_key}"
    return f"title:{title}" if title else ""


def _timestamp(value) -> float | None:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return None


def _probable_switch_identity(sessions: list[dict]) -> str:
    grouped: dict[str, list[dict]] = {}
    for session in sessions:
        identity = _playback_identity(session)
        if identity:
            grouped.setdefault(identity, []).append(session)

    for identity, matches in grouped.items():
        session_keys = {_clean(item.get("session_key")) for item in matches}
        session_keys.discard("")
        if len(matches) < 2 or len(session_keys) < 2:
            continue

        return identity
    return ""


def should_defer_stream_violation(
    *,
    policy_id: int,
    user_key,
    sessions: list[dict],
    limit: int,
    current_count: int,
    now: float | None = None,
) -> bool:
    """Return True during the first five minutes of a probable device switch."""
    now = float(time.time() if now is None else now)
    prefix = f"policy:{int(policy_id)}|user:{user_key}|"

    with _LOCK:
        for key, first_seen in list(_FIRST_SEEN.items()):
            if now - first_seen > _CACHE_RETENTION_SECONDS:
                _FIRST_SEEN.pop(key, None)

        # Grace is deliberately narrow: only one stream above the configured
        # limit. A larger overage is treated as a real violation immediately.
        if current_count <= limit or current_count != limit + 1:
            for key in [key for key in _FIRST_SEEN if key.startswith(prefix)]:
                _FIRST_SEEN.pop(key, None)
            return False

        identity = _probable_switch_identity(sessions)
        if not identity:
            return False

        key = f"{prefix}{identity}"
        first_seen = _FIRST_SEEN.get(key)
        if first_seen is None:
            starts = [
                timestamp
                for timestamp in (
                    _timestamp(item.get("started_at")) or _timestamp(item.get("last_seen_at"))
                    for item in sessions
                    if _playback_identity(item) == identity
                )
                if timestamp is not None
            ]
            if not starts or not 0 <= now - max(starts) <= STREAM_SWITCH_GRACE_SECONDS:
                return False
            first_seen = now
            _FIRST_SEEN[key] = first_seen
        return now - first_seen < STREAM_SWITCH_GRACE_SECONDS


def reset_stream_transition_grace() -> None:
    with _LOCK:
        _FIRST_SEEN.clear()
