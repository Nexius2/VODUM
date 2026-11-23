"""Persistent historical views. HTTP readers never run the expensive builders."""

import json
import sqlite3
import time
from contextlib import nullcontext
from datetime import datetime, timezone

from db_manager import isolated_read_operation
from core.monitoring.precomputed_tabs import default_views


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_precomputed (
    cache_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT,
    computed_at TEXT,
    attempted_at TEXT,
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT
)
"""
DEFAULTS = (("overview", "overview", {}), ("libraries", "libraries", {}),
            ("library_top:30d:all", "library_top", {"library_range": "30d", "library_user_id": None})) + default_views()


def ensure_schema(cursor):
    cursor.execute(SCHEMA)
    for key, kind, options in DEFAULTS:
        cursor.execute("INSERT OR IGNORE INTO monitoring_precomputed(cache_key,kind,options_json) VALUES(?,?,?)",
                       (key, kind, json.dumps(options)))


@isolated_read_operation
def _read(db, key):
    row = db.query_one("SELECT payload_json,computed_at,last_error,requested_at FROM monitoring_precomputed WHERE cache_key=?", (key,))
    return dict(row) if row else None


def load_snapshot(db, key, kind, options=None):
    row = _read(db, key)
    queue_full = False
    if row is None:
        # Register only normalized filters, with a bounded queue. No compute here.
        cursor = db.execute("""INSERT OR IGNORE INTO monitoring_precomputed(cache_key,kind,options_json)
                      SELECT ?,?,? WHERE (SELECT COUNT(*) FROM monitoring_precomputed) < 128""",
                   (key, kind, json.dumps(options or {}, sort_keys=True)))
        queue_full = cursor.rowcount == 0 and _read(db, key) is None
    elif (key not in {item[0] for item in DEFAULTS}
          and row["requested_at"] < datetime.now(timezone.utc).strftime("%Y-%m-%d") + " 00:00:00"):
        # One write at most per day for actively used custom filters.
        db.execute("UPDATE monitoring_precomputed SET requested_at=CURRENT_TIMESTAMP WHERE cache_key=?", (key,))
    payload = json.loads(row["payload_json"]) if row and row["payload_json"] is not None else None
    computed_at = row["computed_at"] if row else None
    age = None
    if computed_at:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(computed_at).replace(tzinfo=timezone.utc)).total_seconds()
    metadata = {"ready": payload is not None, "computed_at": computed_at,
                "stale": age is not None and age > 600, "failed": bool(row and row["last_error"]),
                "queue_full": queue_full}
    return payload, metadata


def load_overview(db, sessions_stats):
    from core.monitoring.overview_aggregates import decorate_monitoring_overview
    payload, metadata = load_snapshot(db, "overview", "overview")
    if payload is not None:
        payload["concurrent_7d"]["peak_streams"] = max(
            int(payload["concurrent_7d"].get("peak_streams") or 0), int(sessions_stats.get("live_sessions") or 0))
        payload = decorate_monitoring_overview(db, payload)
    return payload, metadata


def load_libraries(db, options, growth_period="7"):
    payload, metadata = load_snapshot(db, "libraries", "libraries")
    if payload is None:
        return {"rows": [], "total_rows": 0, "hidden_libraries_count": 0, "users": []}, metadata
    columns = {"server": "server_name", "library": "library_name", "type": "media_type",
               "users": "users_with_access", "items": "item_count", "last": "last_stream_at",
               "plays": "total_plays", "duration": "played_ms"}
    column = columns[options["sort_key"]]
    rows = sorted(payload["rows"], key=lambda row: row["library_id"])
    present = [r for r in rows if r.get(column) is not None]
    absent = [r for r in rows if r.get(column) is None]
    present.sort(key=lambda row: row[column], reverse=options["sort_dir"] == "desc")
    start = max(0, options["offset"])
    payload["rows"] = (present + absent)[start:start + options["per_page"]]
    for row in payload["rows"]:
        row["growth"] = row.get("growth_by_period", {}).get(growth_period)
    return payload, metadata


def load_library_top(db, options):
    from core.monitoring.overview_libraries import build_library_top_cards
    normalized = {"library_range": options["library_range"], "library_user_id": options["library_user_id"]}
    key = f"library_top:{normalized['library_range']}:{normalized['library_user_id'] or 'all'}"
    payload, metadata = load_snapshot(db, key, "library_top", normalized)
    return build_library_top_cards(db, payload) if payload is not None else [], metadata


@isolated_read_operation
def _pending(db):
    keys = tuple(item[0] for item in DEFAULTS)
    marks = ','.join('?' for _ in keys)
    return [dict(row) for row in db.query(f"""
        SELECT cache_key,kind,options_json FROM monitoring_precomputed
        WHERE (computed_at IS NULL OR computed_at <= datetime('now','-5 minutes'))
          AND (attempted_at IS NULL OR attempted_at <= datetime('now','-1 minute'))
          AND (cache_key IN ({marks})
               OR requested_at >= datetime('now','-1 day'))
        ORDER BY COALESCE(computed_at, ''), cache_key
        LIMIT 12
    """, keys)]


@isolated_read_operation
def _compute(db, kind, options):
    from core.monitoring.overview_aggregates import _load_monitoring_overview_aggregates
    from core.monitoring.overview_libraries import (
        load_monitoring_library_table, load_monitoring_library_users, _load_monitoring_library_top_rows,
    )
    if kind == "overview":
        return _load_monitoring_overview_aggregates(db, {}, use_cache=False)
    if kind == "libraries":
        result = load_monitoring_library_table(db, {
            "sort_key": "library", "sort_dir": "asc", "order_sql": "l.name ASC",
            "per_page": 2147483647, "offset": 0,
        })
        result["users"] = load_monitoring_library_users(db)
        return result
    if kind == "library_top":
        return _load_monitoring_library_top_rows(db, options)
    if kind.startswith('tab_'):
        from core.monitoring.precomputed_tabs import compute_tab
        return compute_tab(db, kind[4:], options)
    raise ValueError("Unknown monitoring snapshot kind")


def refresh_snapshots(db, *, budget_seconds=90, compute=_compute):
    # Dedicated read connections keep long calculations off the writer lock.
    # Each completed payload is replaced by one short atomic statement.
    deadline = time.monotonic() + budget_seconds
    completed = errors = 0
    failed_views = []
    keys = tuple(item[0] for item in DEFAULTS)
    marks = ','.join('?' for _ in keys)
    db.execute(f"""DELETE FROM monitoring_precomputed
                  WHERE cache_key NOT IN ({marks})
                    AND requested_at < datetime('now','-7 days')""", keys)
    for row in _pending(db):
        if time.monotonic() >= deadline:
            break
        key = row["cache_key"]
        db.execute("UPDATE monitoring_precomputed SET attempted_at=CURRENT_TIMESTAMP WHERE cache_key=?", (key,))
        try:
            snapshot = getattr(db, "readonly_snapshot", None)
            with snapshot() if snapshot else nullcontext(db) as reader:
                connection = getattr(reader, "connection", None)
                if connection is not None:
                    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
                try:
                    payload = compute(reader, row["kind"], json.loads(row["options_json"]))
                finally:
                    if connection is not None:
                        connection.set_progress_handler(None, 0)
            encoded = json.dumps(payload, ensure_ascii=False)
            db.execute("""UPDATE monitoring_precomputed SET payload_json=?,computed_at=CURRENT_TIMESTAMP,
                          last_error=NULL WHERE cache_key=?""", (encoded, key))
            completed += 1
        except Exception as exc:
            from core.error_reporting import log_handled_failure
            cause = 'view_build_failed'
            if isinstance(exc, sqlite3.OperationalError):
                message = str(exc).lower()
                cause = ('sql_budget_exceeded' if message == 'interrupted'
                         else 'sqlite_missing_table' if message.startswith('no such table:')
                         else 'sqlite_missing_column' if message.startswith('no such column:')
                         else 'sqlite_operation_failed')
            failed_views.append(dict(key=key, cause=cause, error_type=type(exc).__name__))
            log_handled_failure("monitoring.refresh_snapshot", level="error", context={"object_title": key})
            db.execute("UPDATE monitoring_precomputed SET last_error=? WHERE cache_key=?", (str(exc)[:1000], key))
            errors += 1
    result = {"completed": completed, "errors": errors}
    if failed_views:
        result['failed_views'] = failed_views
    return result
