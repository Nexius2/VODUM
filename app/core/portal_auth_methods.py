from __future__ import annotations

import time
from werkzeug.security import check_password_hash


REAUTH_MAX_AGE = 5 * 60


def list_auth_methods(db, portal_account_id: int) -> list[dict]:
    return [dict(row) for row in (db.query(
        "SELECT pai.id,pai.provider,pai.provider_server_id,pai.normalized_identifier,pai.verified_at,s.name AS server_name "
        "FROM portal_auth_identities pai LEFT JOIN servers s ON s.id=pai.provider_server_id "
        "WHERE pai.portal_account_id=? AND pai.is_active=1 ORDER BY pai.provider,pai.id",
        (int(portal_account_id),),
    ) or [])]


def local_reauthentication_valid(db, portal_account_id: int, password: str) -> bool:
    row = db.query_one(
        "SELECT password_hash FROM portal_auth_identities WHERE portal_account_id=? "
        "AND provider='local' AND is_active=1",
        (int(portal_account_id),),
    )
    return bool(row and check_password_hash(row["password_hash"] or "", str(password or "")))


def recently_reauthenticated(session_store, *, now=None) -> bool:
    value = session_store.get("portal_reauthenticated_at")
    try:
        age = int(time.time() if now is None else now) - int(value)
        return 0 <= age <= REAUTH_MAX_AGE
    except (TypeError, ValueError):
        return False


def link_identity(db, portal_account_id: int, provider: str, subject: str, *, server_id=None, identifier=None) -> None:
    provider = str(provider or "").lower(); subject = str(subject or "").strip()
    if provider not in {"plex", "jellyfin"} or not subject:
        raise ValueError("portal_method_invalid")
    existing = db.query_one(
        "SELECT portal_account_id FROM portal_auth_identities WHERE provider=? "
        "AND provider_server_id IS ? AND provider_subject=? AND is_active=1",
        (provider, int(server_id) if server_id is not None else None, subject),
    )
    if existing and int(existing["portal_account_id"]) != int(portal_account_id):
        raise ValueError("portal_method_already_linked")
    if existing:
        return
    db.execute(
        "INSERT INTO portal_auth_identities(portal_account_id,provider,provider_server_id,provider_subject,normalized_identifier,is_active,verified_at) "
        "VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP)",
        (int(portal_account_id), provider, int(server_id) if server_id is not None else None, subject, str(identifier or "").casefold() or None),
    )


def unlink_identity(db, portal_account_id: int, identity_id: int) -> None:
    row = db.query_one(
        "SELECT id FROM portal_auth_identities WHERE id=? AND portal_account_id=? AND is_active=1",
        (int(identity_id), int(portal_account_id)),
    )
    if not row:
        raise ValueError("portal_method_not_found")
    count = db.query_one(
        "SELECT COUNT(*) AS count FROM portal_auth_identities WHERE portal_account_id=? AND is_active=1",
        (int(portal_account_id),),
    )
    if int(count["count"] if count else 0) <= 1:
        raise ValueError("portal_last_method_required")
    db.execute(
        "UPDATE portal_auth_identities SET is_active=0,revoked_at=CURRENT_TIMESTAMP,revoke_reason='user_unlinked',updated_at=CURRENT_TIMESTAMP "
        "WHERE id=? AND portal_account_id=?",
        (int(identity_id), int(portal_account_id)),
    )
