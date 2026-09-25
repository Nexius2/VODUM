"""Bounded grace period for probable playback device switches."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from core.stream_session_identity import extract_machine_identifier


STREAM_SWITCH_GRACE_SECONDS = 300
_CACHE_RETENTION_SECONDS = 3600
_LOCK = threading.RLock()
_FIRST_SEEN: dict[str, float] = {}
_LAST_SEEN: dict[str, float] = {}


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


def _same_actor(first, second):
    if first.get("vodum_user_id") is not None and second.get("vodum_user_id") is not None:
        return first["vodum_user_id"] == second["vodum_user_id"]
    return bool(first.get("external_user_id") and
                first.get("external_user_id") == second.get("external_user_id") and
                first.get("server_id") == second.get("server_id"))


def _switch_pair(first, second):
    if not _same_actor(first, second):
        return False
    a = " ".join(_clean(first.get(k)) for k in ("device", "client_product"))
    b = " ".join(_clean(second.get(k)) for k in ("device", "client_product"))
    same_ip = bool(first.get("ip") and first.get("ip") == second.get("ip"))
    # Equal model/product on one network is ambiguous, even with different
    # machine IDs. Give it a deadline, never a permanent merge.
    same_model = any(first.get(k) and _clean(first[k]) == _clean(second.get(k))
                     for k in ("device", "client_product"))
    def mobile(label):
        fixed = any(word in label for word in ("tv", "shield", "roku", "chromecast", "console", "playstation", "xbox"))
        return not fixed and any(word in label for word in ("phone", "ipad", "tablet", "android", "mobile"))
    same_media = bool(_playback_identity(first) and _playback_identity(first) == _playback_identity(second))
    machine = extract_machine_identifier(first)
    same_machine = bool(machine and machine == extract_machine_identifier(second))
    return same_machine or (same_ip and same_model) or mobile(a) or mobile(b) or same_media


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
        for key in list(_FIRST_SEEN):
            if now - _LAST_SEEN.get(key, _FIRST_SEEN[key]) > _CACHE_RETENTION_SECONDS:
                _FIRST_SEEN.pop(key, None)
                _LAST_SEEN.pop(key, None)

        # Grace is deliberately narrow: only one stream above the configured
        # limit. A larger overage is treated as a real violation immediately.
        if current_count <= limit:
            for key in [key for key in _FIRST_SEEN if key.startswith(prefix)]:
                _FIRST_SEEN.pop(key, None)
                _LAST_SEEN.pop(key, None)
            return False
        if limit <= 0 or current_count != limit + 1:
            return False
        key = f"{prefix}overlap"
        first_seen = _FIRST_SEEN.get(key)
        if first_seen is None:
            starts = []
            for index, first in enumerate(sessions):
                for second in sessions[index + 1:]:
                    if not _switch_pair(first, second):
                        continue
                    pair_starts = [_timestamp(item.get("started_at")) for item in (first, second)]
                    if all(value is not None for value in pair_starts):
                        latest = max(pair_starts)
                        if 0 <= now - latest < STREAM_SWITCH_GRACE_SECONDS:
                            starts.append(latest)
            if not starts:
                return False
            first_seen = min(starts)
            _FIRST_SEEN[key] = first_seen
        _LAST_SEEN[key] = now
        return now - first_seen < STREAM_SWITCH_GRACE_SECONDS


def reset_stream_transition_grace() -> None:
    with _LOCK:
        _FIRST_SEEN.clear()
        _LAST_SEEN.clear()
