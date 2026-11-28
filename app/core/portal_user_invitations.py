"""Server-owned invitation intent; form fields never grant access."""
import json
import re
import secrets
import threading

from core.portal_provider_identity_state import row_media_identity_is_usable
from core.user_phone import normalize_phone

invitation_lock = threading.Lock()


def build_invitation_payload(db, user_id, form):
    source = db.query_one("SELECT * FROM vodum_users WHERE id=?", (user_id,))
    if not source or source["status"] != "active":
        raise ValueError("portal_user_invitation_unavailable")
    source = dict(source)
    email = str(form.get("email") or "").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("portal_invite_email_required")
    if db.query_one("SELECT id FROM vodum_users WHERE lower(trim(email))=? OR lower(trim(second_email))=? "
                    "UNION SELECT vodum_user_id FROM media_users WHERE lower(trim(email))=?", (email, email, email)):
        raise ValueError("portal_user_invitation_email_exists")
    payload = {key: str(form.get(key) or "").strip() for key in ("firstname", "lastname")}
    if any(len(value) > 100 for value in payload.values()):
        raise ValueError("portal_user_invitation_invalid_name")
    payload.update(email=email, phone=normalize_phone(form.get("phone")),
                   username="guest_" + secrets.token_hex(8), referrer_user_id=user_id,
                   subscription_template_id=source.get("subscription_template_id"),
                   expiration_date=source.get("expiration_date"), servers=[])
    accounts = db.query("SELECT mu.* FROM media_users mu JOIN servers s ON s.id=mu.server_id "
                        "WHERE mu.vodum_user_id=? AND lower(mu.type)=lower(s.type) ORDER BY mu.id", (user_id,)) or []
    seen = set()
    jellyfin_password = secrets.token_urlsafe(24)
    for account in accounts:
        account = dict(account)
        sid = int(account["server_id"])
        if sid in seen or not row_media_identity_is_usable(account):
            continue
        libraries = [int(row["id"]) for row in db.query(
            "SELECT l.id FROM media_user_libraries ml JOIN libraries l ON l.id=ml.library_id "
            "WHERE ml.media_user_id=? AND l.server_id=?", (account["id"], sid))]
        if not libraries and account["type"].lower() == "plex":
            continue
        try:
            details = json.loads(account.get("details_json") or "{}")
        except (TypeError, ValueError):
            details = {}
        share = details.get("plex_share") if isinstance(details, dict) else {}
        payload["servers"].append({"server_id": sid, "library_ids": libraries,
                                   "plex_share": share if isinstance(share, dict) else {},
                                   "jellyfin_password": jellyfin_password})
        seen.add(sid)
    if accounts and not payload["servers"]:
        raise ValueError("portal_user_invitation_unavailable")
    return payload, source


def copy_invitation_subscription(db, invited_id, source):
    # Preserve the actual user's snapshot, including custom limits and no-plan users.
    fields = ("subscription_template_id", "expiration_date", "expiration_date_override",
              "max_streams_override", "renewal_method")
    db.execute("UPDATE vodum_users SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
               tuple(source.get(key) for key in fields) + (invited_id,))
    db.execute("INSERT INTO stream_policies(scope_type,scope_id,provider,server_id,is_enabled,priority,rule_type,rule_value_json) "
               "SELECT 'user',?,provider,server_id,is_enabled,priority,rule_type,rule_value_json "
               "FROM stream_policies WHERE scope_type='user' AND scope_id=?",
               (invited_id, source["id"]))
