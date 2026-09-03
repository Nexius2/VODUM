from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone


DEFAULT_ADMIN_SESSION_TTL = timedelta(hours=12)
LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=5)


def _sql_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def create_admin_session(db, *, now=None, ttl=None) -> dict:
    now = now or datetime.now(timezone.utc)
    ttl = DEFAULT_ADMIN_SESSION_TTL if ttl is None else ttl
    if ttl <= timedelta(0):
        raise ValueError("invalid_admin_session_ttl")
    token = secrets.token_urlsafe(32)
    token_hash = _token_hash(token)
    db.execute(
        "INSERT INTO admin_sessions(admin_account_id,token_hash,last_seen_at,expires_at) "
        "VALUES(1,?,?,?)",
        (token_hash, _sql_datetime(now), _sql_datetime(now + ttl)),
    )
    row = db.query_one(
        "SELECT id,expires_at FROM admin_sessions WHERE token_hash=?", (token_hash,)
    )
    if not row:
        raise RuntimeError("admin_session_not_persisted")
    return {"session_id": int(row["id"]), "token": token}


def validate_admin_session(db, session_id: int, token: str, *, now=None, ttl=None) -> bool:
    if not token:
        return False
    row = db.query_one(
        "SELECT token_hash,last_seen_at,expires_at,revoked_at FROM admin_sessions "
        "WHERE id=? AND admin_account_id=1",
        (int(session_id),),
    )
    if not row or row["revoked_at"]:
        return False
    if not secrets.compare_digest(str(row["token_hash"] or ""), _token_hash(token)):
        return False
    current_time = now or datetime.now(timezone.utc)
    ttl = DEFAULT_ADMIN_SESSION_TTL if ttl is None else ttl
    if ttl <= timedelta(0):
        return False
    try:
        expires_at = datetime.fromisoformat(
            str(row["expires_at"]).replace("Z", "+00:00")
        )
        last_seen_at = datetime.fromisoformat(
            str(row["last_seen_at"]).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    if expires_at <= current_time:
        return False
    if current_time - last_seen_at >= LAST_SEEN_WRITE_INTERVAL:
        db.execute(
            "UPDATE admin_sessions SET last_seen_at=?,expires_at=? "
            "WHERE id=? AND revoked_at IS NULL",
            (
                _sql_datetime(current_time),
                _sql_datetime(current_time + ttl),
                int(session_id),
            ),
        )
    return True


def revoke_admin_session(db, session_id: int, *, reason="logout") -> None:
    db.execute(
        "UPDATE admin_sessions SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP),"
        "revoke_reason=COALESCE(revoke_reason,?) WHERE id=? AND admin_account_id=1",
        (str(reason or "revoked")[:80], int(session_id)),
    )
