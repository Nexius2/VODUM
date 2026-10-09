from __future__ import annotations


DASHBOARD_SERVER_LIMIT = 6


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
