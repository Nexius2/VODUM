from __future__ import annotations

def conversation_for_user(db, vodum_user_id: int, *, create: bool = False):
    row = db.query_one(
        """SELECT c.id,c.status,c.created_at,c.updated_at,pa.id AS portal_account_id,
                  vu.id AS vodum_user_id,vu.username,vu.email
           FROM portal_accounts pa JOIN vodum_users vu ON vu.id=pa.vodum_user_id
           LEFT JOIN portal_conversations c ON c.portal_account_id=pa.id
           WHERE pa.vodum_user_id=?""",
        (int(vodum_user_id),),
    )
    row = dict(row) if row else None
    if row and row.get("id") is None and create:
        cur = db.execute("INSERT INTO portal_conversations(portal_account_id) VALUES(?)", (row["portal_account_id"],))
        row["id"] = int(cur.lastrowid)
        row["status"] = "open"
    return row


def list_messages(db, conversation_id: int):
    return [dict(row) for row in (db.query(
        "SELECT id,sender_type,body,created_at FROM portal_messages WHERE conversation_id=? ORDER BY created_at,id",
        (int(conversation_id),),
    ) or [])]


def add_message(db, conversation_id: int, sender_type: str, body: str):
    body = str(body or "").strip()
    if not body or len(body) > 4000:
        raise ValueError("portal_message_invalid")
    db.execute(
        "INSERT INTO portal_messages(conversation_id,sender_type,body,read_by_admin,read_by_user) VALUES(?,?,?,?,?)",
        (int(conversation_id), sender_type, body, 1 if sender_type == "admin" else 0, 1 if sender_type == "user" else 0),
    )
    db.execute("UPDATE portal_conversations SET status='open',updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(conversation_id),))


def mark_read(db, conversation_id: int, reader: str):
    column = "read_by_admin" if reader == "admin" else "read_by_user"
    sender = "user" if reader == "admin" else "admin"
    db.execute(f"UPDATE portal_messages SET {column}=1 WHERE conversation_id=? AND sender_type=?", (int(conversation_id), sender))


def unread_messages_for_user(db, vodum_user_id: int) -> int:
    row = db.query_one(
        """SELECT COUNT(*) AS cnt
           FROM portal_messages m
           JOIN portal_conversations c ON c.id=m.conversation_id
           JOIN portal_accounts pa ON pa.id=c.portal_account_id
           WHERE pa.vodum_user_id=? AND m.sender_type='admin' AND m.read_by_user=0""",
        (int(vodum_user_id),),
    )
    return int(row["cnt"] or 0) if row else 0


def notify_user_of_admin_reply(db, conversation_id: int) -> list:
    """Notify the portal user without rolling back a stored reply on delivery failure."""
    from communications_engine import record_history, send_to_user
    from core.communication_i18n import communication_translate, resolve_communication_language
    from mailing_utils import build_portal_login_url

    user_row = db.query_one(
        """SELECT vu.* FROM vodum_users vu
           JOIN portal_accounts pa ON pa.vodum_user_id=vu.id
           JOIN portal_conversations c ON c.portal_account_id=pa.id
           WHERE c.id=?""",
        (int(conversation_id),),
    )
    settings_row = db.query_one("SELECT * FROM settings WHERE id=1")
    if not user_row or not settings_row:
        return []
    user, settings = dict(user_row), dict(settings_row)
    settings["user_notifications_can_override"] = 1
    language = resolve_communication_language(settings, user)
    variables = {
        "username": user.get("username") or user.get("email") or "",
        "brand_name": str(settings.get("brand_name") or "VODUM").strip(),
        "portal_login_url": build_portal_login_url(settings.get("portal_public_url")),
    }
    subject = communication_translate("portal.direct_message.subject", language, variables)
    body = communication_translate("portal.direct_message.body", language, variables)
    attempts = send_to_user(
        db=db, settings=settings, user=user, subject=subject, body=body,
        attachments=[], bypass_skip_never_used_accounts=True,
    )
    for attempt in attempts:
        record_history(
            db=db, kind="portal_direct_message", template_id=None, campaign_id=None,
            user_id=user.get("id"), attempt=attempt,
            meta={"conversation_id": int(conversation_id)},
        )
    return attempts
