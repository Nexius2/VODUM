import time

from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_enforcer_config import HOUSEHOLD_MEMORY_SECONDS, STREAM_SYNC_GRACE_SECONDS, STREAM_SYNC_TRANSITION_SECONDS
from core.stream_media_transition import is_coherent_media_transition, media_family_key
from core.stream_session_identity import parse_datetime, session_endpoint_identity, session_sort_key


logger = get_logger("stream_enforcer")
STREAM_SYNC_GRACE_CACHE: dict[str, dict] = {}


def _cleanup_cache():
    now = time.time()
    ttl = max(STREAM_SYNC_GRACE_SECONDS * 3, HOUSEHOLD_MEMORY_SECONDS)
    for key in list(STREAM_SYNC_GRACE_CACHE):
        if now - float((STREAM_SYNC_GRACE_CACHE.get(key) or {}).get("ts") or 0) > ttl:
            STREAM_SYNC_GRACE_CACHE.pop(key, None)


def _grace_key(policy_id: int, user_key, endpoint_key: str) -> str:
    # Deliberately exclude session/media identifiers. Otherwise every newly
    # browsed title would create a fresh grace window and could postpone
    # enforcement indefinitely.
    return f"policy:{policy_id}|user:{user_key}|endpoint:{endpoint_key}"


def _is_rapid_transition_chain(sessions: list[dict]) -> bool:
    """Accept a browsing sequence when every consecutive start is close.

    Comparing only the oldest and newest session rejects legitimate users who
    preview several titles in succession. Consecutive gaps preserve that use
    case while a fixed grace deadline still prevents unlimited bypasses.
    """
    starts = []
    for session in sessions:
        parsed = parse_datetime(session.get("started_at") or session.get("last_seen_at"))
        if parsed is None:
            return False
        starts.append(parsed)
    starts.sort()
    return all(
        (current - previous).total_seconds() <= STREAM_SYNC_TRANSITION_SECONDS
        for previous, current in zip(starts, starts[1:])
    )


def _transition_state(sessions: list[dict]) -> tuple[set[str], float, float]:
    keys = {str(session.get("session_key") or "").strip() for session in sessions}
    keys.discard("")
    starts = [
        parsed.timestamp()
        for session in sessions
        if (parsed := parse_datetime(session.get("started_at") or session.get("last_seen_at"))) is not None
    ]
    return keys, min(starts, default=0.0), max(starts, default=0.0)


def deduplicate_user_stream_sessions(policy: dict, user_key, sessions: list[dict]) -> list[dict]:
    if len(sessions) < 2:
        return sessions
    _cleanup_cache()
    groups, passthrough = {}, []
    for session in sessions:
        endpoint_key, strong = session_endpoint_identity(session)
        if not endpoint_key:
            passthrough.append(session)
            continue
        bucket = groups.setdefault(endpoint_key, {"strong": False, "sessions": []})
        bucket["strong"] = bool(bucket["strong"] or strong)
        bucket["sessions"].append(session)
    kept = list(passthrough)
    policy_id = int(policy.get("id") or 0)
    for endpoint_key, bucket in groups.items():
        endpoint_sessions = sorted(bucket["sessions"], key=session_sort_key, reverse=True)
        if len(endpoint_sessions) <= 1:
            kept.extend(endpoint_sessions)
            continue
        representative = endpoint_sessions[0]
        if bucket["strong"]:
            kept.append(representative)
            if is_debug_mode_enabled():
                logger.debug("[stream_sync_dedupe] merged same machine | policy=%s | user=%s | endpoint=%s | sessions=%s", policy_id, user_key, endpoint_key, len(endpoint_sessions))
            continue
        # Plex can replace a playback session while leaving the previous row
        # visible for a short time.  When the endpoint and media are coherent,
        # this is one playback transition, not several simultaneous streams.
        # Keep deduplicating for the whole overlap instead of counting every
        # stale replacement after the generic two-run grace expires.
        if is_coherent_media_transition(endpoint_sessions):
            kept.append(representative)
            if is_debug_mode_enabled():
                logger.debug(
                    "[stream_sync_dedupe] merged coherent playback replacements | policy=%s | user=%s | endpoint=%s | sessions=%s",
                    policy_id,
                    user_key,
                    endpoint_key,
                    len(endpoint_sessions),
                )
            continue
        if not _is_rapid_transition_chain(endpoint_sessions):
            kept.extend(endpoint_sessions)
            continue
        key = _grace_key(policy_id, user_key, endpoint_key)
        now = time.time()
        entry = STREAM_SYNC_GRACE_CACHE.get(key)
        session_keys, earliest_start, latest_start = _transition_state(endpoint_sessions)
        previous_keys = set((entry or {}).get("session_keys") or ())
        previous_latest_start = float((entry or {}).get("latest_start") or 0)
        is_distinct_later_burst = bool(
            entry
            and session_keys
            and previous_keys
            and session_keys.isdisjoint(previous_keys)
            and earliest_start - previous_latest_start > STREAM_SYNC_TRANSITION_SECONDS
        )
        if entry is None or is_distinct_later_burst:
            entry = {"first_seen": now, "ts": now}
        else:
            entry["ts"] = now
        entry["session_keys"] = sorted(session_keys)
        entry["latest_start"] = latest_start
        STREAM_SYNC_GRACE_CACHE[key] = entry
        elapsed = now - float(entry.get("first_seen") or now)
        if elapsed < STREAM_SYNC_GRACE_SECONDS:
            kept.append(representative)
            logger.info(
                "[stream_sync_grace] probable same-device browsing overlap | policy=%s | user=%s | endpoint=%s | sessions=%s | elapsed=%ss/%ss",
                policy_id, user_key, endpoint_key, len(endpoint_sessions), int(elapsed), STREAM_SYNC_GRACE_SECONDS,
            )
        else:
            logger.warning(
                "[stream_sync_grace] weak same-device overlap persisted beyond grace, counting all streams | policy=%s | user=%s | endpoint=%s | sessions=%s | elapsed=%ss",
                policy_id, user_key, endpoint_key, len(endpoint_sessions), int(elapsed),
            )
            kept.extend(endpoint_sessions)
    return kept
