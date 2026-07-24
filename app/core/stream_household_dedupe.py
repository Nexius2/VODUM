import time
from typing import Dict, List

from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_enforcer_config import HOUSEHOLD_MEMORY_SECONDS
from core.stream_session_identity import household_match_score, is_probable_same_household


logger = get_logger("stream_enforcer")
RECENT_SESSION_CACHE: Dict[str, List[dict]] = {}


def deduplicate_household_sessions(sessions: List[dict]) -> List[dict]:
    kept = []

    cleanup_recent_session_cache()

    enriched_sessions = []
    seen_session_keys = set()

    for sess in sessions:
        session_key = str(sess.get("session_key") or "")

        if session_key and session_key not in seen_session_keys:
            enriched_sessions.append(sess)
            seen_session_keys.add(session_key)

        user_key = str(
            sess.get("vodum_user_id")
            or sess.get("external_user_id")
            or "unknown"
        )

        previous = RECENT_SESSION_CACHE.get(user_key, [])

        for old_sess in previous:
            old_key = str(old_sess.get("session_key") or "")

            # Avoid reprocessing same session repeatedly
            if old_key and old_key in seen_session_keys:
                continue

            enriched_sessions.append(old_sess)

            if old_key:
                seen_session_keys.add(old_key)

    for sess in enriched_sessions:
        duplicate = False

        for existing in kept:
            if is_probable_same_household(sess, existing):
                duplicate = True

                if is_debug_mode_enabled():
                    logger.debug(
                        "[household_dedupe] merged sessions | user=%s | ip_a=%s | ip_b=%s | device_a=%s | device_b=%s | title_a=%s | title_b=%s | score=%s",
                        sess.get("media_username") or sess.get("external_user_id"),
                        sess.get("ip"),
                        existing.get("ip"),
                        sess.get("device"),
                        existing.get("device"),
                        sess.get("title"),
                        existing.get("title"),
                        household_match_score(sess, existing),
                    )

                break

        if not duplicate:
            kept.append(sess)

            user_key = str(
                sess.get("vodum_user_id")
                or sess.get("external_user_id")
                or "unknown"
            )

            cache_entry = dict(sess)
            cache_entry["_cache_ts"] = time.time()

            RECENT_SESSION_CACHE.setdefault(user_key, []).append(cache_entry)

            # sécurité mémoire
            if len(RECENT_SESSION_CACHE[user_key]) > 25:
                RECENT_SESSION_CACHE[user_key] = RECENT_SESSION_CACHE[user_key][-25:]

    if is_debug_mode_enabled():
        if is_debug_mode_enabled():
            logger.debug(
                "[smart_household] dedupe result original=%s kept=%s",
                len(sessions),
                len(kept),
            )

    return kept

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

