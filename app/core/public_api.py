"""Read-only HTTP API for dashboards (Homepage, Grafana, scripts).

Access uses named tokens created by the admin. Only the SHA-256 of a token is
stored; the token itself is shown once at creation. Each token carries scopes
that limit which endpoints it may read. Responses never contain emails, IP
addresses, locations, server URLs or credentials, payments, notes or logs.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque

SCOPES = ("stats", "servers", "sessions", "users")
TOKEN_PREFIX = "vodum_"
NAME_MAX_LENGTH = 60
MAX_ACTIVE_TOKENS = 20
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60
LIVE_WINDOW_SECONDS = 300
EXPIRING_SOON_DAYS = 7
USER_STATUSES = (
    "active", "pre_expired", "reminder", "expired",
    "invited", "unfriended", "suspended", "unknown",
)

SCHEMA = """CREATE TABLE IF NOT EXISTS api_tokens (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE,
 scopes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_used_at TEXT,
 use_count INTEGER NOT NULL DEFAULT 0,
 revoked_at TEXT
);
"""


class ApiTokenError(ValueError):
    """A token request the admin must correct; the message is a translation key."""


def hash_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def normalize_scopes(values) -> list[str]:
    chosen = {str(value or "").strip().lower() for value in values or []}
    return [scope for scope in SCOPES if scope in chosen]


def create_token(db, name, scopes) -> tuple[int, str]:
    """Store a new token and return (id, token). The token is never stored."""
    name = " ".join(str(name or "").split())[:NAME_MAX_LENGTH]
    if not name:
        raise ApiTokenError("api_token_name_required")
    scopes = normalize_scopes(scopes)
    if not scopes:
        raise ApiTokenError("api_token_scope_required")
    active = db.query_one("SELECT COUNT(*) AS n FROM api_tokens WHERE revoked_at IS NULL")
    if active and int(active["n"] or 0) >= MAX_ACTIVE_TOKENS:
        raise ApiTokenError("api_token_limit_reached")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    cursor = db.execute(
        "INSERT INTO api_tokens(name, token_hash, scopes) VALUES (?, ?, ?)",
        (name, hash_token(token), ",".join(scopes)),
    )
    return int(cursor.lastrowid), token


def revoke_token(db, token_id) -> bool:
    try:
        token_id = int(token_id)
    except (TypeError, ValueError):
        return False
    cursor = db.execute(
        "UPDATE api_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE id=? AND revoked_at IS NULL",
        (token_id,),
    )
    return bool(getattr(cursor, "rowcount", 0))


def list_tokens(db) -> list[dict]:
    rows = db.query(
        """SELECT id, name, scopes, created_at, last_used_at, use_count, revoked_at
           FROM api_tokens ORDER BY revoked_at IS NOT NULL, id DESC"""
    ) or []
    tokens = []
    for row in rows:
        item = dict(row)
        item["scopes"] = [scope for scope in str(item.get("scopes") or "").split(",") if scope]
        tokens.append(item)
    return tokens


def extract_request_token(headers) -> str:
    """Read the token from Authorization: Bearer or X-Api-Key, never the URL."""
    authorization = str(headers.get("Authorization") or "").strip()
    if authorization[:7].lower() == "bearer ":
        return authorization[7:].strip()
    return str(headers.get("X-Api-Key") or "").strip()


def find_active_token(db, token: str):
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    row = db.query_one(
        "SELECT id, name, scopes FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",
        (hash_token(token),),
    )
    if not row:
        return None
    item = dict(row)
    item["scopes"] = [scope for scope in str(item.get("scopes") or "").split(",") if scope]
    return item


def record_token_use(db, token_id: int) -> None:
    db.execute(
        "UPDATE api_tokens SET last_used_at=CURRENT_TIMESTAMP, use_count=use_count+1 WHERE id=?",
        (int(token_id),),
    )


class RateLimiter:
    """Sliding window per token, kept in memory for this process."""

    def __init__(self, limit=RATE_LIMIT_REQUESTS, window=RATE_LIMIT_WINDOW_SECONDS, clock=time.monotonic):
        self.limit = int(limit)
        self.window = float(window)
        self.clock = clock
        self._hits: dict[int, deque] = {}
        self._lock = threading.Lock()

    def check(self, key) -> int:
        """Return 0 when allowed, otherwise the seconds to wait."""
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# Data loaders: only aggregate or display fields, no personal contact data.
# ---------------------------------------------------------------------------

def _server_state(status) -> str:
    status = str(status or "").strip().lower()
    if status == "up":
        return "online"
    if status == "down":
        return "offline"
    return "unknown"


def _live_sql() -> str:
    return f"-{int(LIVE_WINDOW_SECONDS)} seconds"


def load_stats(db) -> dict:
    from core.monitoring.snapshots import get_live_session_stats

    live = get_live_session_stats(db, live_window_seconds=LIVE_WINDOW_SECONDS, fallback_max_age_seconds=600)
    users = db.query_one(
        """SELECT
             COALESCE(SUM(CASE WHEN status IN ('active','pre_expired','reminder') THEN 1 ELSE 0 END), 0) AS active,
             COALESCE(SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END), 0) AS expired,
             COALESCE(SUM(CASE WHEN status IN ('active','pre_expired','reminder')
                     AND expiration_date IS NOT NULL
                     AND date(expiration_date) >= date('now')
                     AND date(expiration_date) <= date('now', ?) THEN 1 ELSE 0 END), 0) AS expiring_soon
           FROM vodum_users""",
        (f"+{EXPIRING_SOON_DAYS} days",),
    )
    servers = {"online": 0, "offline": 0, "unknown": 0}
    for row in db.query("SELECT status FROM servers") or []:
        servers[_server_state(row["status"])] += 1
    return {
        "sessions": {
            "live": int(live.get("live_sessions") or 0),
            "transcodes": int(live.get("transcodes") or 0),
            "direct_plays": int(live.get("direct_plays") or 0),
        },
        "users": {
            "active": int(users["active"] or 0) if users else 0,
            "expired": int(users["expired"] or 0) if users else 0,
            "expiring_soon": int(users["expiring_soon"] or 0) if users else 0,
            "expiring_soon_days": EXPIRING_SOON_DAYS,
        },
        "servers": {"total": sum(servers.values()), **servers},
    }


def load_servers(db) -> list[dict]:
    from core.monitoring.resource_stats import load_server_resource_stats

    rows = [dict(row) for row in db.query("SELECT id, name, type, status FROM servers ORDER BY name COLLATE NOCASE, id") or []]
    live = {
        int(row["server_id"]): (int(row["live"] or 0), int(row["transcodes"] or 0))
        for row in db.query(
            """SELECT server_id, COUNT(*) AS live,
                      COALESCE(SUM(CASE WHEN is_transcode=1 THEN 1 ELSE 0 END), 0) AS transcodes
               FROM media_sessions WHERE datetime(last_seen_at) >= datetime('now', ?)
               GROUP BY server_id""",
            (_live_sql(),),
        ) or []
    }
    resources = load_server_resource_stats(db, [row["id"] for row in rows])
    result = []
    for row in rows:
        sessions, transcodes = live.get(int(row["id"]), (0, 0))
        resource = resources.get(int(row["id"])) or {}
        result.append({
            "id": int(row["id"]),
            "name": row.get("name") or "",
            "type": str(row.get("type") or "").strip().lower(),
            "status": _server_state(row.get("status")),
            "live_sessions": sessions,
            "transcodes": transcodes,
            "cpu_pct": resource.get("server_cpu_pct"),
            "ram_pct": resource.get("server_ram_pct"),
        })
    return result


def load_sessions(db) -> list[dict]:
    from core.monitoring.mappers import apply_playback_username
    from core.monitoring.overview_live import _apply_progress
    from core.monitoring.video_quality import describe_video_quality

    rows = db.query(
        """SELECT ms.media_type, ms.title, ms.grandparent_title, ms.parent_title, ms.state,
                  ms.progress_ms, ms.duration_ms, ms.is_transcode, ms.raw_json,
                  s.name AS server_name, s.type AS provider,
                  COALESCE(NULLIF(TRIM(vu.username), ''), mu.username) AS username
           FROM media_sessions ms
           JOIN servers s ON s.id = ms.server_id
           LEFT JOIN media_users mu ON mu.id = ms.media_user_id
           LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
           WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
           ORDER BY ms.id ASC""",
        (_live_sql(),),
    ) or []
    result = []
    for row in rows:
        session = dict(row)
        apply_playback_username(session)
        _apply_progress(session)
        quality = describe_video_quality(session.get("provider"), session.get("raw_json")) or {}
        result.append({
            "title": session.get("title") or "",
            "grandparent_title": session.get("grandparent_title") or None,
            "parent_title": session.get("parent_title") or None,
            "media_type": session.get("media_type") or None,
            "state": session.get("state") or None,
            "server": session.get("server_name") or "",
            "provider": str(session.get("provider") or "").strip().lower(),
            "username": session.get("username") or None,
            "progress_pct": session.get("progress_pct") or 0,
            "progress_ms": int(session.get("progress_ms") or 0),
            "duration_ms": int(session.get("duration_ms") or 0),
            "playback": "transcode" if int(session.get("is_transcode") or 0) == 1 else "direct",
            "video_source": quality.get("source"),
            "video_stream": quality.get("stream"),
            "video_transcoded": bool(quality.get("video_transcoded")),
        })
    return result


def load_users_summary(db) -> dict:
    by_status = {status: 0 for status in USER_STATUSES}
    total = 0
    for row in db.query("SELECT status, COUNT(*) AS n FROM vodum_users GROUP BY status") or []:
        status = str(row["status"] or "unknown")
        count = int(row["n"] or 0)
        by_status[status if status in by_status else "unknown"] += count
        total += count
    by_subscription = [
        {"name": row["name"] if row["name"] is not None else None, "users": int(row["n"] or 0)}
        for row in db.query(
            """SELECT st.name AS name, COUNT(*) AS n
               FROM vodum_users vu
               LEFT JOIN subscription_templates st ON st.id = vu.subscription_template_id
               GROUP BY st.name ORDER BY n DESC, st.name"""
        ) or []
    ]
    return {"total": total, "by_status": by_status, "by_subscription": by_subscription}
