from __future__ import annotations

import math

from db_manager import isolated_read_operation


DASHBOARD_SERVER_LIMIT = 6


@isolated_read_operation
def load_dashboard_server_resources(db, servers):
    """Reuse recent monitoring measurements for the displayed cards only."""
    from core.monitoring.resource_stats import load_server_resource_stats
    from web.helpers import table_exists

    rows = [dict(server) for server in servers]
    if not table_exists(db, 'monitoring_server_resources'):
        return rows
    online = [row['id'] for row in rows if row.get('status') == 'up']
    resources = load_server_resource_stats(db, online, max_age_seconds=600)
    for row in rows:
        resource = resources.get(int(row['id']), {}) if row.get('status') == 'up' else {}
        for key in ('server_cpu_pct', 'server_ram_pct'):
            row[key] = None
            if not resource.get('server_resource_available') or resource.get(key) is None:
                continue
            try:
                value = float(resource[key])
                if math.isfinite(value) and value >= 0:
                    row[key] = min(100, value)
            except (TypeError, ValueError):
                pass
    return rows


def dashboard_server_preview(servers, limit: int = DASHBOARD_SERVER_LIMIT) -> list[dict]:
    rows = [dict(server) for server in (servers or [])]
    rows.sort(
        key=lambda server: (
            0 if str(server.get("status") or "").strip().lower() == "up" else 1,
            -int(server.get("peak_streams_7d") or 0),
            str(server.get("name") or "").casefold(),
        )
    )
    return rows[:max(0, int(limit))]


def dashboard_server_initial_preview(servers):
    """Render known server state without waiting for historical aggregates."""
    from core.aggregate_cache import peek_aggregate
    rows = [dict(server) for server in (servers or [])]
    snapshot = peek_aggregate("dashboard:server-peaks:7d")
    peaks = {int(row["server_id"]): int(row["peak"] or 0) for row in (snapshot or [])}
    for server in rows:
        server["peak_streams_7d"] = peaks.get(int(server["id"]))
    return dashboard_server_preview(rows)
