from logging_utils import get_logger
from core.stream_session_identity import extract_machine_identifier


logger = get_logger("stream_enforcer")


def log_sessions(user_key: str, sessions: list[dict], reason: str):
    logger.warning(
        "[policy_debug] user=%s reason=%s session_count=%s",
        user_key, reason, len(sessions),
    )
    for index, session in enumerate(sessions, start=1):
        logger.warning(
            "[policy_debug] #%s | title=%s | grandparent=%s | ip=%s | device=%s | client=%s | transcode=%s | state=%s | started=%s | last_seen=%s | session_key=%s | machine=%s",
            index, session.get("title"), session.get("grandparent_title"),
            session.get("ip"), session.get("device"), session.get("client_product"),
            session.get("is_transcode"), session.get("state"), session.get("started_at"),
            session.get("last_seen_at"), session.get("session_key"),
            extract_machine_identifier(session),
        )
