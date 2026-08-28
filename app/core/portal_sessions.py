from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from core.portal_account_state import state_allows_portal


DEFAULT_SESSION_TTL = timedelta(days=14)
LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=5)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sql_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def hash_session_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def create_portal_session(db, portal_account_id: int, *, now=None, ttl=None) -> dict:
    now = now or _utcnow()
    ttl = DEFAULT_SESSION_TTL if ttl is None else ttl
    if ttl <= timedelta(0):
        raise ValueError("invalid_session_ttl")
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)
    db.execute(
        """
        INSERT INTO portal_sessions(
            portal_account_id, token_hash, created_at, last_seen_at, expires_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(portal_account_id), token_hash, _sql_datetime(now),
            _sql_datetime(now), _sql_datetime(now + ttl),
        ),
    )
    row = db.query_one(
        "SELECT id, expires_at FROM portal_sessions WHERE token_hash = ?",
        (token_hash,),
    )
    if not row:
        raise RuntimeError("portal_session_not_persisted")
    return {"session_id": int(row["id"]), "token": token, "expires_at": row["expires_at"]}


def validate_portal_session(db, session_id: int, token: str, *, now=None, touch=True) -> dict | None:
    if not token:
        return None
    now = now or _utcnow()
    row = db.query_one(
        """
        SELECT ps.id, ps.portal_account_id, ps.token_hash, ps.last_seen_at,
               ps.expires_at, ps.revoked_at, pa.vodum_user_id, pa.status,
               vu.status AS user_status
        FROM portal_sessions ps
        JOIN portal_accounts pa ON pa.id = ps.portal_account_id
        JOIN vodum_users vu ON vu.id = pa.vodum_user_id
        WHERE ps.id = ?
        """,
        (int(session_id),),
    )
    if not row or row["revoked_at"] or not state_allows_portal(row["status"], row["user_status"]):
        return None
    expected = str(row["token_hash"] or "")
    if not secrets.compare_digest(expected, hash_session_token(token)):
        return None
    expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        return None
    last_seen = datetime.fromisoformat(str(row["last_seen_at"]).replace("Z", "+00:00"))
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if touch and now - last_seen >= LAST_SEEN_WRITE_INTERVAL:
        db.execute(
            "UPDATE portal_sessions SET last_seen_at = ? WHERE id = ? AND revoked_at IS NULL",
            (_sql_datetime(now), int(row["id"])),
        )
    return {
        "session_id": int(row["id"]),
        "portal_account_id": int(row["portal_account_id"]),
        "vodum_user_id": int(row["vodum_user_id"]),
        "expires_at": row["expires_at"],
    }


def revoke_portal_session(db, session_id: int, *, reason="logout") -> None:
    db.execute(
        """
        UPDATE portal_sessions
        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
            revoke_reason = COALESCE(revoke_reason, ?)
        WHERE id = ?
        """,
        (str(reason or "revoked")[:80], int(session_id)),
    )


def revoke_portal_account_sessions(db, portal_account_id: int, *, reason="account_revoked") -> None:
    db.execute(
        """
        UPDATE portal_sessions
        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
            revoke_reason = COALESCE(revoke_reason, ?)
        WHERE portal_account_id = ?
        """,
        (str(reason or "revoked")[:80], int(portal_account_id)),
    )


def revoke_other_portal_sessions(db, portal_account_id: int, current_session_id: int, *, reason="security_change") -> None:
    db.execute(
        "UPDATE portal_sessions SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP),"
        "revoke_reason=COALESCE(revoke_reason,?) WHERE portal_account_id=? AND id<>?",
        (str(reason or "security_change")[:80], int(portal_account_id), int(current_session_id)),
    )
