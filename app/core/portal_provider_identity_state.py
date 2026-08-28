from __future__ import annotations

import json


INACTIVE_PRESENCES = {"removed", "disabled"}


def _presence(raw) -> str:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        value = {}
    return str(value.get("provider_presence") or "present").strip().lower()


def reconcile_portal_provider_identity(db, media_user_id: int) -> dict:
    """Mirror provider presence into portal login identities without merging servers."""
    portal_columns = db.query("PRAGMA table_info(portal_auth_identities)") or []
    if not portal_columns:
        return {"changed": False, "reason": "portal_schema_unavailable"}
    media_columns = {
        str(item["name"] if not hasattr(item, "keys") or "name" in item.keys() else "")
        for item in (db.query("PRAGMA table_info(media_users)") or [])
    }
    username_expression = "username" if "username" in media_columns else "NULL AS username"
    row = db.query_one(
        f"SELECT id,server_id,type,external_user_id,{username_expression},details_json FROM media_users WHERE id=?",
        (int(media_user_id),),
    )
    if not row:
        return {"changed": False, "reason": "media_user_missing"}
    account = dict(row); provider = str(account.get("type") or "").lower()
    subject = str(account.get("external_user_id") or "").strip()
    presence = _presence(account.get("details_json"))
    if provider not in {"plex", "jellyfin"} or not subject:
        return {"changed": False, "reason": "identity_missing"}

    server_id = int(account["server_id"]) if provider == "jellyfin" else None
    if presence in INACTIVE_PRESENCES and provider == "plex":
        siblings = db.query(
            "SELECT id,details_json FROM media_users WHERE type='plex' AND external_user_id=? AND id<>?",
            (subject, int(media_user_id)),
        ) or []
        if any(_presence(item["details_json"]) not in INACTIVE_PRESENCES for item in siblings):
            return {"changed": False, "reason": "active_on_other_server"}

    if presence in INACTIVE_PRESENCES:
        db.execute(
            "UPDATE portal_auth_identities SET is_active=0,revoked_at=CURRENT_TIMESTAMP,revoke_reason=?,updated_at=CURRENT_TIMESTAMP "
            "WHERE provider=? AND provider_server_id IS ? AND provider_subject=? AND is_active=1",
            (f"provider_{presence}", provider, server_id, subject),
        )
        return {"changed": True, "state": presence}

    # A provider identity that returns may be restored only when VODUM itself
    # revoked it because the provider had marked it removed/disabled.
    db.execute(
        "UPDATE portal_auth_identities SET is_active=1,revoked_at=NULL,revoke_reason=NULL,"
        "normalized_identifier=?,updated_at=CURRENT_TIMESTAMP "
        "WHERE provider=? AND provider_server_id IS ? AND provider_subject=? "
        "AND is_active=0 AND revoke_reason IN ('provider_removed','provider_disabled')",
        (str(account.get("username") or "").strip().casefold() or None, provider, server_id, subject),
    )
    # A rename only refreshes the display/login hint; the stable subject remains unchanged.
    db.execute(
        "UPDATE portal_auth_identities SET normalized_identifier=?,updated_at=CURRENT_TIMESTAMP "
        "WHERE provider=? AND provider_server_id IS ? AND provider_subject=? AND is_active=1",
        (str(account.get("username") or "").strip().casefold() or None, provider, server_id, subject),
    )
    return {"changed": True, "state": "present"}


def media_identity_is_usable(details_json) -> bool:
    return _presence(details_json) not in INACTIVE_PRESENCES


def row_media_identity_is_usable(row) -> bool:
    try:
        raw = row.get("details_json") if hasattr(row, "get") else row["details_json"]
    except (KeyError, IndexError, TypeError):
        raw = None
    return media_identity_is_usable(raw)
