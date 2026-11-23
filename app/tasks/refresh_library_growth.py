"""Refresh the monitoring library growth summaries from Plex and Jellyfin."""

import json
import time
from datetime import datetime, timezone

from core.monitoring.library_growth import GROWTH_LIBRARIES, scan_growth
from core.server_cooldown import should_skip_unreachable_server
from core.server_page_queries import LIBRARY_TYPE_SQL
from secret_store import decrypt_server_record


LIBRARY_SCAN_BUDGET_SECONDS = 30 * 60


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
    for library in libraries:
        server_id = library['server_id']
        if server_id not in servers:
            server = db.query_one('SELECT * FROM servers WHERE id = ?', (server_id,))
            servers[server_id] = decrypt_server_record(server) if server else None
        server = servers[server_id]
        if not server or should_skip_unreachable_server(server):
            skipped += 1
            task_logs(task_id, 'warning', f"refresh_library_growth: library={library['id']} server={server_id} "
                      "reason=server_unavailable; scan skipped, previous measurement retained")
            continue

        now = datetime.now(timezone.utc)
        started_at = time.monotonic()
        deadline = started_at + LIBRARY_SCAN_BUDGET_SECONDS

        def heartbeat():
            if time.monotonic() >= deadline:
                raise TimeoutError('Library growth scan exceeded its budget')

        try:
            totals = scan_growth(server, dict(library), now, heartbeat)
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

    return {'status': 'warning' if skipped else 'ok', 'libraries': updated, 'skipped': skipped}
