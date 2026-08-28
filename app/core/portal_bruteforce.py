from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone


MAX_ATTEMPTS = 5
WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)


def _now(value=None):
    return value or datetime.now(timezone.utc)


def _sql(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def scope_hash(scope: str, value: str) -> str:
    normalized = str(value or "").strip().casefold()
    return hashlib.sha256(f"portal:{scope}:{normalized}".encode()).hexdigest()


def login_locked(db, scope: str, value: str, *, now=None) -> bool:
    row = db.query_one(
        "SELECT locked_until FROM portal_login_attempts WHERE scope=? AND scope_hash=?",
        (scope, scope_hash(scope, value)),
    )
    locked_until = _parse(row["locked_until"]) if row else None
    return bool(locked_until and locked_until > _now(now))


def register_login_failure(db, scope: str, value: str, *, now=None) -> bool:
    now = _now(now)
    hashed = scope_hash(scope, value)
    with db.transaction() as cursor:
        cursor.execute(
            "SELECT failed_attempts,first_failed_at FROM portal_login_attempts "
            "WHERE scope=? AND scope_hash=?",
            (scope, hashed),
        )
        row = cursor.fetchone()
        first = _parse(row[1]) if row else None
        count = int(row[0] or 0) if row else 0
        if not first or now - first >= WINDOW:
            first, count = now, 0
        count += 1
        locked_until = now + LOCK_DURATION if count >= MAX_ATTEMPTS else None
        cursor.execute(
            """
            INSERT INTO portal_login_attempts(
                scope,scope_hash,failed_attempts,first_failed_at,last_failed_at,locked_until
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(scope,scope_hash) DO UPDATE SET
                failed_attempts=excluded.failed_attempts,
                first_failed_at=excluded.first_failed_at,
                last_failed_at=excluded.last_failed_at,
                locked_until=excluded.locked_until
            """,
            (scope, hashed, count, _sql(first), _sql(now), _sql(locked_until) if locked_until else None),
        )
    return locked_until is not None


def clear_login_failures(db, scope: str, value: str) -> None:
    db.execute(
        "DELETE FROM portal_login_attempts WHERE scope=? AND scope_hash=?",
        (scope, scope_hash(scope, value)),
    )
