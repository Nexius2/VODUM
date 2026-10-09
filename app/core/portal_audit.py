from __future__ import annotations

import hashlib
import json


ALLOWED_EVENTS = {
    "account_activated", "invitation_sent", "login_failed", "login_locked",
    "login_success", "logout", "password_reset_completed", "password_reset_requested",
    "admin_invitation_revoked", "admin_account_suspended", "admin_account_reactivated",
    "admin_forced_logout", "admin_auth_reset",
    "turnstile_failed",
    "jellyfin_login_success", "jellyfin_login_failed", "jellyfin_login_locked", "activation_plex_verified",
    "session_started", "page_view", "profile_updated", "password_changed",
    "friend_invitation", "identity_linked", "identity_unlinked", "reauthentication",
    "media_requested", "media_profile_updated", "support_message_sent",
}
SAFE_DETAIL_KEYS = {"reason", "method", "provider", "action", "status", "page", "media_kind", "external_id", "media_title", "request_result"}


def _fingerprint(kind: str, value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(f"portal-audit:{kind}:{normalized}".encode()).hexdigest()


def record_portal_event(
    db, event_type: str, outcome: str, *, portal_account_id=None,
    client_ip=None, user_agent=None, details=None,
) -> None:
    if event_type not in ALLOWED_EVENTS:
        raise ValueError("invalid_portal_audit_event")
    if outcome not in {"success", "failure", "blocked"}:
        raise ValueError("invalid_portal_audit_outcome")
    safe_details = {
        str(key)[:40]: value
        for key, value in dict(details or {}).items()
        if str(key) in SAFE_DETAIL_KEYS
        and (event_type == 'media_requested' or str(key) not in {'media_kind','external_id','media_title','request_result'})
        and isinstance(value, (str, int, float, bool, type(None)))
    }
    db.execute(
        """
        INSERT INTO portal_audit_events(
            portal_account_id,event_type,outcome,ip_hash,user_agent_hash,details_json
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            int(portal_account_id) if portal_account_id is not None else None,
            event_type, outcome, _fingerprint("ip", client_ip),
            _fingerprint("ua", user_agent), json.dumps(safe_details, separators=(",", ":")),
        ),
    )
    from logging_utils import get_logger
    logger = get_logger("portal_audit")
    log = logger.info if outcome == "success" else logger.warning
    user_id = None
    if portal_account_id is not None and hasattr(db, "query_one"):
        account = db.query_one("SELECT vodum_user_id FROM portal_accounts WHERE id=?", (int(portal_account_id),))
        if account:
            user_id = account["vodum_user_id"]
    log("Portal event=%s outcome=%s account_id=%s user_id=%s details=%s",
        event_type, outcome, portal_account_id, user_id, json.dumps(safe_details, separators=(",", ":")))
