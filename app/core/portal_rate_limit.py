from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone


def portal_request_allowed(db, route_scope: str, client_ip: str, *, limit=30, window=timedelta(minutes=15), now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    start = now - window
    key = hashlib.sha256(f"portal-rate:{route_scope}:{client_ip}".encode()).hexdigest()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = start.strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cursor:
        cursor.execute("DELETE FROM portal_request_limits WHERE window_started_at<?", (cutoff,))
        cursor.execute("SELECT request_count FROM portal_request_limits WHERE scope_hash=?", (key,))
        row = cursor.fetchone()
        if row and int(row[0]) >= int(limit):
            return False
        cursor.execute(
            "INSERT INTO portal_request_limits(scope_hash,window_started_at,request_count) VALUES(?,?,1) "
            "ON CONFLICT(scope_hash) DO UPDATE SET request_count=request_count+1",
            (key, timestamp),
        )
    return True
