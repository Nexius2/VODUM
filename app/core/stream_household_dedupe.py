import time
from typing import Dict, List

from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_enforcer_config import HOUSEHOLD_MEMORY_SECONDS


logger = get_logger("stream_enforcer")
RECENT_SESSION_CACHE: Dict[str, List[dict]] = {}


def deduplicate_household_sessions(sessions: List[dict]) -> List[dict]:
    cleanup_recent_session_cache()

    # Only sessions returned by the current live-session query may participate
    # in policy counts.  The former implementation appended entries kept in
    # RECENT_SESSION_CACHE for up to five minutes.  Those historical entries
    # could keep an IP violation alive after Plex had already removed the
    # session, causing repeated attempts to terminate a session that no longer
    # existed.
    current_sessions = []
    seen_session_keys = set()

    for sess in sessions:
        session_key = (
            int(sess.get("server_id") or 0),
            str(sess.get("session_key") or ""),
        )

        if session_key[1] and session_key not in seen_session_keys:
            current_sessions.append(sess)
            seen_session_keys.add(session_key)

    # Preserve independent playback sessions. Endpoint/model similarities
    # are handled by bounded policy grace, not permanent household merging.
    return current_sessions


def cleanup_recent_session_cache():
    now = time.time()

    for user_key in list(RECENT_SESSION_CACHE.keys()):
        kept = []

        for sess in RECENT_SESSION_CACHE[user_key]:
            ts = sess.get("_cache_ts", 0)

            if (now - ts) <= HOUSEHOLD_MEMORY_SECONDS:
                kept.append(sess)

        if kept:
            RECENT_SESSION_CACHE[user_key] = kept
        else:
            if is_debug_mode_enabled():
                logger.debug(
                    "[smart_household] cleanup cache user=%s",
                    user_key,
                )

            RECENT_SESSION_CACHE.pop(user_key, None)
