from __future__ import annotations

from core.communication_i18n import communication_translate, resolve_communication_language


def portal_email_payload(db, vodum_user_id: int, event: str, variables=None) -> dict | None:
    user = db.query_one(
        """
        SELECT vu.email,vu.username,
          (SELECT preferred_language FROM media_users WHERE vodum_user_id=vu.id
           AND TRIM(COALESCE(preferred_language,''))<>'' ORDER BY id LIMIT 1) AS preferred_language
        FROM vodum_users vu WHERE vu.id=?
        """,
        (int(vodum_user_id),),
    )
    if not user or not str(user["email"] or "").strip():
        return None
    settings = db.query_one("SELECT communication_language FROM settings WHERE id=1") or {}
    language = resolve_communication_language(dict(settings), dict(user))
    values = {"username": user["username"] or "", **dict(variables or {})}
    return {
        "to": str(user["email"]).strip(), "language": language,
        "subject": communication_translate(f"portal.{event}.subject", language, values),
        "body": communication_translate(f"portal.{event}.body", language, values),
    }
