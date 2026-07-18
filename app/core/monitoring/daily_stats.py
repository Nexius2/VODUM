"""Materialized daily Monitoring aggregates.

The source history remains authoritative.  These rows are disposable and can
be rebuilt safely; they only make common multi-day overview reads bounded.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def _day_value(value) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def materialize_day(db, day) -> dict:
    """Replace one daily aggregate atomically from session history."""
    day = _day_value(day)
    rows = [dict(row) for row in (db.query(
        """
        WITH ranked AS (
          SELECT
            h.id,
            h.server_id,
            h.media_key,
            h.media_type,
            h.title,
            h.grandparent_title,
            COALESCE(CAST(vu.id AS TEXT), 'media:' || CAST(mu.id AS TEXT),
                     'external:' || NULLIF(TRIM(h.external_user_id), ''), 'unknown') AS viewer_id,
            COALESCE(vu.username, mu.username, '-') AS username,
            MIN(COALESCE(h.watch_ms, 0), CASE WHEN COALESCE(h.duration_ms, 0) > 0
                 THEN h.duration_ms ELSE COALESCE(h.watch_ms, 0) END) AS watch_ms,
            ROW_NUMBER() OVER (
              PARTITION BY h.server_id,
                COALESCE(CAST(vu.id AS TEXT), 'media:' || CAST(mu.id AS TEXT),
                         'external:' || NULLIF(TRIM(h.external_user_id), ''), 'unknown'),
                COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media'),
                strftime('%Y-%m-%d %H:%M', h.started_at)
              ORDER BY h.stopped_at DESC, h.id DESC
            ) AS rn
          FROM media_session_history h
          LEFT JOIN media_users mu ON mu.id = h.media_user_id
          LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
          WHERE h.stopped_at >= ? AND h.stopped_at < datetime(?, '+1 day')
        )
        SELECT * FROM ranked WHERE rn = 1
        """,
        (day, day),
    ) or [])]

    viewers = sorted({str(row["viewer_id"]) for row in rows if row.get("viewer_id")})
    watch_ms = sum(max(0, int(row.get("watch_ms") or 0)) for row in rows)

    users = {}
    media = {}
    for row in rows:
        viewer_id = str(row.get("viewer_id") or "unknown")
        user = users.setdefault(viewer_id, {"key": viewer_id, "username": row.get("username") or "-", "sessions": 0, "watch_ms": 0})
        user["sessions"] += 1
        user["watch_ms"] += max(0, int(row.get("watch_ms") or 0))

        title = (row.get("grandparent_title") or row.get("title") or "-").strip() or "-"
        media_key = f"{row.get('server_id')}|{row.get('media_type') or 'unknown'}|{row.get('media_key') or title.lower()}"
        item = media.setdefault(media_key, {"key": media_key, "title": title, "media_type": row.get("media_type") or "unknown", "sessions": 0, "watch_ms": 0, "viewers": set()})
        item["sessions"] += 1
        item["watch_ms"] += max(0, int(row.get("watch_ms") or 0))
        item["viewers"].add(viewer_id)

    top_users = sorted(users.values(), key=lambda item: (item["watch_ms"], item["sessions"]), reverse=True)[:25]
    top_media = []
    for item in media.values():
        item["viewers"] = len(item["viewers"])
        top_media.append(item)
    top_media.sort(key=lambda item: (item["viewers"], item["watch_ms"], item["sessions"]), reverse=True)
    top_media = top_media[:25]

    db.execute(
        """
        INSERT INTO monitoring_daily_stats(
          day, sessions, watch_ms, active_users, viewer_keys_json,
          top_users_json, top_media_json, source_max_id, computed_at
        ) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(day) DO UPDATE SET
          sessions=excluded.sessions, watch_ms=excluded.watch_ms,
          active_users=excluded.active_users, viewer_keys_json=excluded.viewer_keys_json,
          top_users_json=excluded.top_users_json, top_media_json=excluded.top_media_json,
          source_max_id=excluded.source_max_id, computed_at=CURRENT_TIMESTAMP
        """,
        (day, len(rows), watch_ms, len(viewers), _json(viewers), _json(top_users),
         _json(top_media), max((int(row.get("id") or 0) for row in rows), default=0)),
    )
    return {"day": day, "sessions": len(rows), "watch_ms": watch_ms, "active_users": len(viewers)}


def refresh_recent_days(db, days: int = 31, *, today=None) -> dict:
    today = date.fromisoformat(_day_value(today or datetime.now(timezone.utc)))
    days = max(1, min(int(days), 366))
    results = [materialize_day(db, today - timedelta(days=offset)) for offset in range(days)]
    return {"days": len(results), "sessions": sum(item["sessions"] for item in results)}


def load_materialized_window(db, days: int) -> dict | None:
    """Return compact window statistics, or None when coverage is incomplete."""
    days = max(1, min(int(days), 366))
    rows = [dict(row) for row in (db.query(
        """SELECT day,sessions,watch_ms,viewer_keys_json,top_users_json,top_media_json
           FROM monitoring_daily_stats
           WHERE day >= date('now', ?) ORDER BY day DESC""",
        (f"-{days - 1} days",),
    ) or [])]
    if len(rows) < days:
        return None

    viewers = set()
    users = {}
    media = {}
    for row in rows:
        viewers.update(str(value) for value in _loads(row.get("viewer_keys_json"), []))
        for item in _loads(row.get("top_users_json"), []):
            key = str(item.get("key") or item.get("username") or "-")
            merged = users.setdefault(key, {"username": item.get("username") or "-", "sessions": 0, "watch_ms": 0})
            merged["sessions"] += int(item.get("sessions") or 0)
            merged["watch_ms"] += int(item.get("watch_ms") or 0)
        for item in _loads(row.get("top_media_json"), []):
            key = str(item.get("key") or item.get("title") or "-")
            merged = media.setdefault(key, {"title": item.get("title") or "-", "media_type": item.get("media_type") or "unknown", "sessions": 0, "watch_ms": 0, "viewers": 0})
            for field in ("sessions", "watch_ms", "viewers"):
                merged[field] += int(item.get(field) or 0)

    sessions = sum(int(row.get("sessions") or 0) for row in rows)
    watch_ms = sum(int(row.get("watch_ms") or 0) for row in rows)
    return {
        "sessions": sessions,
        "active_users": len(viewers),
        "total_watch_ms": watch_ms,
        "avg_watch_ms": (watch_ms / sessions) if sessions else 0,
        "top_users": sorted(users.values(), key=lambda item: (item["watch_ms"], item["sessions"]), reverse=True)[:10],
        "top_media": sorted(media.values(), key=lambda item: (item["viewers"], item["watch_ms"]), reverse=True)[:10],
    }
