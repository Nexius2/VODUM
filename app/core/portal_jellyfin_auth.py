from __future__ import annotations

from dataclasses import dataclass

import requests

from core.http_security import server_http_session
from secret_store import decrypt_server_record
from core.portal_provider_identity_state import row_media_identity_is_usable
from core.portal_account_state import ensure_provider_portal_account


@dataclass(frozen=True)
class JellyfinUserIdentity:
    server_id: int
    subject: str
    username: str


class JellyfinPortalAuthError(ValueError):
    pass


def _server_bases(server: dict) -> list[str]:
    result = []
    for key in ("url", "local_url", "public_url"):
        value = str(server.get(key) or "").strip().rstrip("/")
        if value.startswith(("http://", "https://")) and value not in result:
            result.append(value)
    return result


def authenticate_jellyfin_user(db, server_id: int, username: str, password: str) -> JellyfinUserIdentity:
    """Authenticate directly against one configured server without retaining credentials."""
    row = db.query_one(
        "SELECT id,name,type,url,local_url,public_url,token,settings_json FROM servers "
        "WHERE id=? AND LOWER(type)='jellyfin'",
        (int(server_id),),
    )
    clean_username = str(username or "").strip()
    if not row or not clean_username or not password:
        raise JellyfinPortalAuthError("portal_invalid_credentials")
    server = decrypt_server_record(row)
    http = server_http_session(server, default_timeout=15)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": 'MediaBrowser Client="VODUM Portal", Device="Web", DeviceId="vodum-portal", Version="1"',
    }
    for base in _server_bases(server):
        try:
            response = http.post(
                f"{base}/Users/AuthenticateByName",
                headers=headers,
                json={"Username": clean_username, "Pw": str(password)},
            )
            if response.status_code in (401, 403):
                raise JellyfinPortalAuthError("portal_invalid_credentials")
            response.raise_for_status()
            payload = response.json() or {}
            user = payload.get("User") or {}
            subject = str(user.get("Id") or "").strip()
            if not subject or not payload.get("AccessToken"):
                raise JellyfinPortalAuthError("portal_invalid_credentials")
            return JellyfinUserIdentity(int(server_id), subject, str(user.get("Name") or clean_username))
        except JellyfinPortalAuthError:
            raise
        except (requests.RequestException, ValueError, TypeError):
            continue
    raise JellyfinPortalAuthError("portal_jellyfin_unavailable")


def resolve_jellyfin_portal_account(db, identity: JellyfinUserIdentity) -> dict | None:
    linked = db.query_one(
        "SELECT pai.portal_account_id,pa.vodum_user_id FROM portal_auth_identities pai "
        "JOIN portal_accounts pa ON pa.id=pai.portal_account_id "
        "WHERE pai.provider='jellyfin' AND pai.provider_server_id=? "
        "AND pai.provider_subject=? AND pai.is_active=1",
        (identity.server_id, identity.subject),
    )
    if linked:
        return dict(linked)
    rows = db.query(
        "SELECT vodum_user_id,details_json FROM media_users WHERE type='jellyfin' "
        "AND server_id=? AND external_user_id=? AND vodum_user_id IS NOT NULL",
        (identity.server_id, identity.subject),
    ) or []
    candidates = {int(row["vodum_user_id"]) for row in rows if row_media_identity_is_usable(row)}
    if len(candidates) != 1:
        return None
    vodum_user_id = next(iter(candidates))
    account_id = ensure_provider_portal_account(db, vodum_user_id)
    if account_id is None:
        return None
    db.execute(
        "INSERT INTO portal_auth_identities(portal_account_id,provider,provider_server_id,provider_subject,normalized_identifier,is_active,verified_at) "
        "VALUES(?,'jellyfin',?,?,?,1,CURRENT_TIMESTAMP)",
        (account_id, identity.server_id, identity.subject, identity.username.casefold()),
    )
    return {"portal_account_id": account_id, "vodum_user_id": vodum_user_id}
