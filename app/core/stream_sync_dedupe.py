import time

from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_enforcer_config import HOUSEHOLD_MEMORY_SECONDS, STREAM_SYNC_GRACE_RUNS, STREAM_SYNC_TRANSITION_SECONDS
from core.stream_media_transition import media_family_key
from core.stream_session_identity import session_endpoint_identity, session_sort_key, session_time_delta_seconds


logger = get_logger("stream_enforcer")
STREAM_SYNC_GRACE_CACHE: dict[str, dict] = {}


def _cleanup_cache():
    now = time.time()
    ttl = max(STREAM_SYNC_TRANSITION_SECONDS * 3, HOUSEHOLD_MEMORY_SECONDS)
    for key in list(STREAM_SYNC_GRACE_CACHE):
        if now - float((STREAM_SYNC_GRACE_CACHE.get(key) or {}).get("ts") or 0) > ttl:
            STREAM_SYNC_GRACE_CACHE.pop(key, None)


def _grace_key(policy_id: int, user_key, endpoint_key: str, sessions: list[dict]) -> str:
    parts = [f"{s.get('server_id')}:{s.get('session_key')}:{media_family_key(s)}" for s in sessions]
    return f"policy:{policy_id}|user:{user_key}|endpoint:{endpoint_key}|" + "|".join(sorted(parts))


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
        max_delta = max(session_time_delta_seconds(representative, session) for session in endpoint_sessions[1:])
        if max_delta > STREAM_SYNC_TRANSITION_SECONDS:
            kept.extend(endpoint_sessions)
            continue
        key = _grace_key(policy_id, user_key, endpoint_key, endpoint_sessions)
        entry = STREAM_SYNC_GRACE_CACHE.get(key) or {"runs": 0, "ts": time.time()}
        entry.update(runs=int(entry.get("runs") or 0) + 1, ts=time.time())
        STREAM_SYNC_GRACE_CACHE[key] = entry
        if entry["runs"] <= STREAM_SYNC_GRACE_RUNS:
            kept.append(representative)
            logger.info("[stream_sync_grace] probable same-device sync overlap | policy=%s | user=%s | endpoint=%s | sessions=%s | run=%s/%s", policy_id, user_key, endpoint_key, len(endpoint_sessions), entry["runs"], STREAM_SYNC_GRACE_RUNS)
        else:
            logger.warning("[stream_sync_grace] weak same-device overlap persisted, counting all streams | policy=%s | user=%s | endpoint=%s | sessions=%s", policy_id, user_key, endpoint_key, len(endpoint_sessions))
            kept.extend(endpoint_sessions)
    return kept
