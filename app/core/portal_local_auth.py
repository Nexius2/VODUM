from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from core.auth_principal import portal_principal
from core.portal_sessions import create_portal_session
from core.portal_password_policy import password_policy_error
from core.portal_account_state import state_allows_portal


INVITATION_TTL = timedelta(days=7)
PASSWORD_RESET_TTL = timedelta(hours=1)


def _sql(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode()).hexdigest()


def normalize_email(email: str) -> str:
    return str(email or "").strip().casefold()


def create_local_invitation(db, vodum_user_id: int, email: str, *, now=None) -> dict:
    normalized = normalize_email(email)
    if not normalized or normalized.count("@") != 1 or " " in normalized:
        raise ValueError("portal_email_invalid")
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    token_hash = _token_hash(token)
    with db.transaction() as cursor:
        cursor.execute(
            "INSERT INTO portal_accounts(vodum_user_id,status) VALUES(?, 'invited') "
            "ON CONFLICT(vodum_user_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP",
            (int(vodum_user_id),),
        )
        cursor.execute("SELECT id FROM portal_accounts WHERE vodum_user_id=?", (int(vodum_user_id),))
        account_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT OR IGNORE INTO portal_account_roles(portal_account_id,role_id) "
            "SELECT ?,id FROM portal_roles WHERE name='user'",
            (account_id,),
        )
        cursor.execute(
            "UPDATE portal_account_tokens SET revoked_at=? WHERE portal_account_id=? "
            "AND purpose='invitation' AND used_at IS NULL AND revoked_at IS NULL",
            (_sql(now), account_id),
        )
        cursor.execute(
            """
            INSERT INTO portal_auth_identities(
                portal_account_id,provider,provider_subject,normalized_identifier,is_active
            ) VALUES(?, 'local', ?, ?, 0)
            ON CONFLICT(normalized_identifier) WHERE provider='local' AND normalized_identifier IS NOT NULL
            DO UPDATE SET updated_at=CURRENT_TIMESTAMP
            """,
            (account_id, normalized, normalized),
        )
        cursor.execute(
            "SELECT portal_account_id FROM portal_auth_identities "
            "WHERE provider='local' AND normalized_identifier=?",
            (normalized,),
        )
        identity_owner = cursor.fetchone()
        if not identity_owner or int(identity_owner[0]) != account_id:
            raise ValueError("portal_email_in_use")
        cursor.execute(
            "INSERT INTO portal_account_tokens(portal_account_id,purpose,token_hash,created_at,expires_at) "
            "VALUES(?, 'invitation', ?, ?, ?)",
            (account_id, token_hash, _sql(now), _sql(now + INVITATION_TTL)),
        )
    return {"portal_account_id": account_id, "token": token, "expires_at": _sql(now + INVITATION_TTL)}


def activate_local_invitation(db, token: str, password: str, *, now=None) -> int:
    error = password_policy_error(password, db.query_one("SELECT portal_password_min_length,portal_password_require_upper,portal_password_require_lower,portal_password_require_digit,portal_password_require_symbol FROM settings WHERE id=1"))
    if error: raise ValueError(error)
    now = now or datetime.now(timezone.utc)
    with db.transaction() as cursor:
        cursor.execute(
            """
            SELECT t.id, t.portal_account_id
            FROM portal_account_tokens t
            JOIN portal_accounts pa ON pa.id=t.portal_account_id
            WHERE t.token_hash=? AND t.purpose='invitation' AND t.used_at IS NULL
              AND t.revoked_at IS NULL AND t.expires_at>? AND pa.status='invited'
            """,
            (_token_hash(token), _sql(now)),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("portal_invitation_invalid")
        account_id = int(row[1])
        cursor.execute(
            "UPDATE portal_auth_identities SET password_hash=?,is_active=1,verified_at=?,revoked_at=NULL,revoke_reason=NULL,updated_at=? "
            "WHERE portal_account_id=? AND provider='local'",
            (generate_password_hash(password), _sql(now), _sql(now), account_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("portal_invitation_identity_missing")
        cursor.execute(
            "UPDATE portal_accounts SET status='active',email_verified_at=?,updated_at=? WHERE id=?",
            (_sql(now), _sql(now), account_id),
        )
        cursor.execute("UPDATE portal_account_tokens SET used_at=? WHERE id=?", (_sql(now), int(row[0])))
    return account_id


def invitation_is_valid(db, token: str, *, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    return db.query_one(
        """
        SELECT t.id FROM portal_account_tokens t
        JOIN portal_accounts pa ON pa.id=t.portal_account_id
        WHERE t.token_hash=? AND t.purpose='invitation' AND t.used_at IS NULL
          AND t.revoked_at IS NULL AND t.expires_at>? AND pa.status='invited'
        """,
        (_token_hash(token), _sql(now)),
    ) is not None


def revoke_invitation(db, token: str) -> None:
    db.execute(
        "UPDATE portal_account_tokens SET revoked_at=CURRENT_TIMESTAMP "
        "WHERE token_hash=? AND purpose='invitation' AND used_at IS NULL",
        (_token_hash(token),),
    )


def create_password_reset(db, email: str, *, now=None) -> dict | None:
    normalized = normalize_email(email)
    row = db.query_one(
        """
        SELECT pai.portal_account_id,pa.vodum_user_id
        FROM portal_auth_identities pai
        JOIN portal_accounts pa ON pa.id=pai.portal_account_id
        WHERE pai.provider='local' AND pai.normalized_identifier=?
          AND pai.is_active=1 AND pa.status='active'
        """,
        (normalized,),
    )
    if not row:
        return None
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    with db.transaction() as cursor:
        cursor.execute(
            "UPDATE portal_account_tokens SET revoked_at=? WHERE portal_account_id=? "
            "AND purpose='password_reset' AND used_at IS NULL AND revoked_at IS NULL",
            (_sql(now), int(row["portal_account_id"])),
        )
        cursor.execute(
            "INSERT INTO portal_account_tokens(portal_account_id,purpose,token_hash,created_at,expires_at) "
            "VALUES(?, 'password_reset', ?, ?, ?)",
            (int(row["portal_account_id"]), _token_hash(token), _sql(now), _sql(now + PASSWORD_RESET_TTL)),
        )
    return {
        "portal_account_id": int(row["portal_account_id"]),
        "vodum_user_id": int(row["vodum_user_id"]),
        "token": token,
        "expires_at": _sql(now + PASSWORD_RESET_TTL),
    }


def password_reset_is_valid(db, token: str, *, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    return db.query_one(
        "SELECT id FROM portal_account_tokens WHERE token_hash=? AND purpose='password_reset' "
        "AND used_at IS NULL AND revoked_at IS NULL AND expires_at>?",
        (_token_hash(token), _sql(now)),
    ) is not None


def revoke_password_reset(db, token: str) -> None:
    db.execute(
        "UPDATE portal_account_tokens SET revoked_at=CURRENT_TIMESTAMP "
        "WHERE token_hash=? AND purpose='password_reset' AND used_at IS NULL",
        (_token_hash(token),),
    )


def consume_password_reset(db, token: str, password: str, *, now=None) -> int:
    error = password_policy_error(password, db.query_one("SELECT portal_password_min_length,portal_password_require_upper,portal_password_require_lower,portal_password_require_digit,portal_password_require_symbol FROM settings WHERE id=1"))
    if error: raise ValueError(error)
    now = now or datetime.now(timezone.utc)
    with db.transaction() as cursor:
        cursor.execute(
            "SELECT id,portal_account_id FROM portal_account_tokens WHERE token_hash=? "
            "AND purpose='password_reset' AND used_at IS NULL AND revoked_at IS NULL AND expires_at>?",
            (_token_hash(token), _sql(now)),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("portal_reset_invalid")
        account_id = int(row[1])
        cursor.execute(
            "UPDATE portal_auth_identities SET password_hash=?,updated_at=? "
            "WHERE portal_account_id=? AND provider='local' AND is_active=1",
            (generate_password_hash(password), _sql(now), account_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("portal_reset_invalid")
        cursor.execute("UPDATE portal_account_tokens SET used_at=? WHERE id=?", (_sql(now), int(row[0])))
        cursor.execute(
            "UPDATE portal_sessions SET revoked_at=COALESCE(revoked_at,?), "
            "revoke_reason=COALESCE(revoke_reason,'password_reset') WHERE portal_account_id=?",
            (_sql(now), account_id),
        )
    return account_id


def authenticate_local_user(db, email: str, password: str, *, now=None, session_ttl=None) -> dict | None:
    normalized = normalize_email(email)
    row = db.query_one(
        """
        SELECT pai.id AS identity_id,pai.portal_account_id,pai.password_hash,pa.vodum_user_id,
               pa.status AS account_status,vu.status AS user_status
        FROM portal_auth_identities pai
        JOIN portal_accounts pa ON pa.id=pai.portal_account_id
        JOIN vodum_users vu ON vu.id=pa.vodum_user_id
        WHERE pai.provider='local' AND pai.normalized_identifier=?
          AND pai.is_active=1
        """,
        (normalized,),
    )
    if not row or not state_allows_portal(row["account_status"], row["user_status"]) or not check_password_hash(row["password_hash"] or "", str(password or "")):
        return None
    created = create_portal_session(
        db, int(row["portal_account_id"]), now=now, ttl=session_ttl
    )
    login_at = _sql(now or datetime.now(timezone.utc))
    db.execute(
        "UPDATE portal_auth_identities SET last_login_at=?,updated_at=? WHERE id=?",
        (login_at, login_at, int(row["identity_id"])),
    )
    db.execute(
        "UPDATE portal_accounts SET last_login_at=?,updated_at=? WHERE id=?",
        (login_at, login_at, int(row["portal_account_id"])),
    )
    return portal_principal(
        portal_account_id=int(row["portal_account_id"]),
        vodum_user_id=int(row["vodum_user_id"]),
        session_id=created["session_id"], session_token=created["token"], email=normalized,
    )


def change_local_password(db, portal_account_id: int, current_password: str, new_password: str) -> None:
    row = db.query_one(
        "SELECT id,password_hash FROM portal_auth_identities WHERE portal_account_id=? AND provider='local' AND is_active=1",
        (int(portal_account_id),),
    )
    if not row or not check_password_hash(row["password_hash"] or "", str(current_password or "")):
        raise ValueError("portal_current_password_invalid")
    settings = db.query_one(
        "SELECT portal_password_min_length,portal_password_require_upper,portal_password_require_lower,portal_password_require_digit,portal_password_require_symbol FROM settings WHERE id=1"
    ) or {}
    from core.portal_password_policy import password_policy_error
    error = password_policy_error(new_password, settings)
    if error:
        raise ValueError(error)
    db.execute(
        "UPDATE portal_auth_identities SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (generate_password_hash(str(new_password)), int(row["id"])),
    )
