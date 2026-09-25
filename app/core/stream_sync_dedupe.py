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
        prefix = f"policy:{int(policy.get('id') or 0)}|user:{user_key}|"
        for key in list(STREAM_SYNC_GRACE_CACHE):
            if key.startswith(prefix):
                STREAM_SYNC_GRACE_CACHE.pop(key, None)
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
        # Even a strong device ID can expose multiple persistent playbacks.
        # Only collapse temporarily; count all sessions after the deadline.
        if not (bucket["strong"] or is_coherent_media_transition(endpoint_sessions)
                or _is_rapid_transition_chain(endpoint_sessions)):
            kept.extend(endpoint_sessions)
            continue
        key = _grace_key(policy_id, user_key, endpoint_key)
        now = time.time()
        entry = STREAM_SYNC_GRACE_CACHE.get(key)
        if entry is None:
            entry = {"first_seen": now, "ts": now}
        else:
            entry["ts"] = now
        STREAM_SYNC_GRACE_CACHE[key] = entry
        elapsed = now - float(entry["first_seen"])
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
