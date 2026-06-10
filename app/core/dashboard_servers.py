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
