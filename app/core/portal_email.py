from __future__ import annotations

from core.communication_i18n import communication_translate, resolve_communication_language
from mailing_utils import build_portal_login_url


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
    settings = dict(db.query_one(
        "SELECT communication_language,brand_name,portal_public_url FROM settings WHERE id=1"
    ) or {})
    language = resolve_communication_language(settings, dict(user))
    values = {
        "username": user["username"] or "",
        "brand_name": str(settings.get("brand_name") or "VODUM").strip(),
        "portal_login_url": build_portal_login_url(settings.get("portal_public_url")),
        **dict(variables or {}),
    }
    return {
        "to": str(user["email"]).strip(), "language": language,
        "subject": communication_translate(f"portal.{event}.subject", language, values),
        "body": communication_translate(f"portal.{event}.body", language, values),
    }
