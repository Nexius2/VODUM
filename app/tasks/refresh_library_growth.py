"""Refresh the monitoring library growth summaries from Plex and Jellyfin."""

import json
import time
from datetime import datetime, timedelta, timezone

from core.monitoring.library_growth import (
    GROWTH_LIBRARIES,
    HISTORY_TIME_FORMAT,
    PERIODS,
    SIZE_HISTORY_RETENTION_DAYS,
    net_growth,
    scan_growth,
)
from core.server_cooldown import is_server_in_cooldown
from core.server_page_queries import LIBRARY_TYPE_SQL
from secret_store import decrypt_server_record


LIBRARY_SCAN_BUDGET_SECONDS = 30 * 60


def _record_size_snapshot(db, library_id, now, totals):
    """Append this scan's library size and add net growth to each period.

    The snapshot is stored only after a complete scan, so a failed or partial
    scan never becomes a baseline. Older snapshots beyond the longest period
    are pruned; the latest one before that limit is kept as a baseline.
    """
    library = totals.get('library')
    if not library:
        return totals
    measured_at = now.strftime(HISTORY_TIME_FORMAT)
    db.execute(
        "INSERT INTO monitoring_library_size_history (library_id, measured_at, total_items, total_bytes, missing) "
        "VALUES (?, ?, ?, ?, ?)",
        (library_id, measured_at, library['items'], library['bytes'], library['missing']),
    )
    limit = (now - timedelta(days=SIZE_HISTORY_RETENTION_DAYS)).strftime(HISTORY_TIME_FORMAT)
    db.execute(
        "DELETE FROM monitoring_library_size_history WHERE library_id = ? AND measured_at < ? "
        "AND id <> (SELECT id FROM monitoring_library_size_history WHERE library_id = ? AND measured_at < ? "
        "ORDER BY measured_at DESC, id DESC LIMIT 1)",
        (library_id, limit, library_id, limit),
    )
    history = [
        (row['measured_at'], row['total_bytes'], row['missing'], row['total_items'])
        for row in db.query(
            "SELECT measured_at, total_bytes, missing, total_items FROM monitoring_library_size_history "
            "WHERE library_id = ? ORDER BY measured_at, id",
            (library_id,),
        )
    ]
    for days in PERIODS:
        growth = net_growth(history, now, days)
        if growth and str(days) in totals:
            totals[str(days)].update(growth)
    return totals


def _server_was_marked_down(server):
    return str(server.get('status') or '').strip().lower() == 'down'


def _is_connection_failure(exc):
    import requests

    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError))


def run(task_id, db):
    from tasks_engine import task_logs

    libraries = db.query(f"""
        SELECT l.id, l.server_id, l.section_id, l.type, {LIBRARY_TYPE_SQL} AS normalized_type
        FROM libraries l JOIN servers s ON s.id = l.server_id
        WHERE {GROWTH_LIBRARIES}
        ORDER BY l.server_id, l.id
    """)
    servers = {}
    updated = skipped = 0

    def load_server(server_id):
        if server_id not in servers:
            server = db.query_one('SELECT * FROM servers WHERE id = ?', (server_id,))
            servers[server_id] = decrypt_server_record(server) if server else None
        return servers[server_id]

    def skip(library, reason):
        nonlocal skipped
        skipped += 1
        task_logs(task_id, 'warning', f"refresh_library_growth: library={library['id']} server={library['server_id']} "
                  f"reason={reason}; scan skipped, previous measurement retained")

    def scan(library, server):
        nonlocal updated, skipped
        server_id = library['server_id']
        now = datetime.now(timezone.utc)
        started_at = time.monotonic()
        deadline = started_at + LIBRARY_SCAN_BUDGET_SECONDS

        def heartbeat():
            if time.monotonic() >= deadline:
                raise TimeoutError('Library growth scan exceeded its budget')

        try:
            totals = scan_growth(server, dict(library), now, heartbeat)
            totals = _record_size_snapshot(db, library['id'], now, totals)
            db.execute("""
                INSERT INTO monitoring_library_growth (library_id, measured_at, totals_json, last_attempt_at, last_error)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(library_id) DO UPDATE SET
                    measured_at = excluded.measured_at,
                    totals_json = excluded.totals_json,
                    last_attempt_at = excluded.last_attempt_at, last_error = NULL
            """, (library['id'], now.strftime('%Y-%m-%d %H:%M UTC'), json.dumps(totals), now.strftime('%Y-%m-%d %H:%M UTC')))
            updated += 1
            task_logs(task_id, 'info', f"refresh_library_growth: library={library['id']} server={server_id} "
                      f"scan completed elapsed_seconds={time.monotonic() - started_at:.1f} "
                      f"budget_seconds={LIBRARY_SCAN_BUDGET_SECONDS}")
        except Exception as exc:
            if _server_was_marked_down(server) and _is_connection_failure(exc):
                # Still unreachable: same outcome as a skipped server, not a scan error.
                skip(library, 'server_unavailable')
                return
            skipped += 1
            reason = 'budget_exceeded' if isinstance(exc, TimeoutError) else 'scan_failed'
            db.execute("""
                INSERT INTO monitoring_library_growth(library_id,measured_at,totals_json,last_attempt_at,last_error)
                VALUES (?, '', '{}', ?, ?)
                ON CONFLICT(library_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                    last_error=excluded.last_error
            """, (library['id'], now.strftime('%Y-%m-%d %H:%M UTC'), reason))
            task_logs(task_id, 'warning', f"refresh_library_growth: Library growth unavailable: library={library['id']} server={server_id} "
                      f"provider={server['type']} reason={reason} exception={type(exc).__name__} "
                      f"elapsed_seconds={time.monotonic() - started_at:.1f} "
                      f"budget_seconds={LIBRARY_SCAN_BUDGET_SECONDS}; previous measurement retained")

    # A server stays "down" after one failed monitoring poll until the next
    # server check (every 30 min), even when it answers again. Only an active
    # cooldown postpones the scan; it is retried once after the other libraries.
    deferred = []
    for library in libraries:
        server = load_server(library['server_id'])
        if not server:
            skip(library, 'server_unavailable')
        elif is_server_in_cooldown(server):
            deferred.append(library)
        else:
            scan(library, server)

    servers.clear()
    for library in deferred:
        server = load_server(library['server_id'])
        if not server or is_server_in_cooldown(server):
            skip(library, 'server_unavailable')
        else:
            scan(library, server)

    return {'status': 'warning' if skipped else 'ok', 'libraries': updated, 'skipped': skipped}
