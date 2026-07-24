import time
from datetime import datetime

from communications_engine import enqueue_named_task, schedule_template_notification
from logging_utils import get_logger, is_debug_mode_enabled


logger = get_logger("stream_enforcer")


def media_title_from_session(session: dict) -> str:
    parts = [
        str(session.get(field) or "").strip()
        for field in ("grandparent_title", "parent_title", "title")
    ]
    parts = [part for part in parts if part]
    return " - ".join(parts)


def policy_display_name(policy: dict) -> str:
    rule_type = str(policy.get("rule_type") or "").strip()
    if rule_type:
        return rule_type
    try:
        return f"Policy #{int(policy.get('id'))}"
    except Exception:
        return "Policy"


def queue_stream_blocked_notification(
    db, *, task_id: int, policy: dict, server_row: dict, target: dict,
    reason: str, kill_reason_for_client: str, policy_context_builder,
) -> None:
    vodum_user_id = target.get("vodum_user_id")
    if vodum_user_id is None:
        return
    try:
        vodum_user_id = int(vodum_user_id)
    except Exception:
        return
    template = db.query_one("""
        SELECT id FROM comm_templates
        WHERE key = 'stream_blocked' AND enabled = 1 LIMIT 1
    """)
    if not template:
        return
    server_id = target.get("server_id") or server_row.get("id")
    provider = str(target.get("provider") or server_row.get("type") or "plex").strip().lower()
    if provider not in ("plex", "jellyfin"):
        provider = "plex"
    payload = {
        "trigger_event": "stream_blocked",
        "policy_id": policy.get("id"),
        "policy_name": policy_display_name(policy),
        "policy_reason": kill_reason_for_client or reason or "Policy violation",
        "reason": reason or "",
        "media_title": media_title_from_session(target),
        "server_name": server_row.get("name") or "",
        "client_name": target.get("client_name") or target.get("client_product") or "",
        "device_name": target.get("device") or target.get("client_product") or "",
        "blocked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_key": target.get("session_key") or "",
        "server_id": server_id,
        "provider": provider,
        **policy_context_builder(),
    }
    dedupe_key = (
        f"stream_blocked:policy:{policy.get('id')}:user:{vodum_user_id}:"
        f"server:{server_id}:session:{target.get('session_key')}:at:{int(time.time())}"
    )
    try:
        schedule_template_notification(
            db=db, template_id=int(template["id"]), user_id=vodum_user_id,
            provider=provider, server_id=int(server_id) if server_id is not None else None,
            send_at_modifier=None, payload=payload, dedupe_key=dedupe_key,
            max_attempts=10,
        )
        enqueue_named_task(db, "send_expiration_emails")
        if is_debug_mode_enabled():
            logger.debug(
                "[stream_enforcer] stream_blocked notification queued user=%s policy=%s server=%s",
                vodum_user_id, policy.get("id"), server_id,
            )
    except Exception as exc:
        logger.warning(
            "[TASK %s] stream_enforcer: failed to queue stream_blocked notification: %s",
            task_id, exc, exc_info=True,
        )
