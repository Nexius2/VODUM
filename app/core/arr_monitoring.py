"""ARR availability, API latency, download queue and health history."""
import time
from core.http_security import server_http_session

SCHEMA = 'CREATE TABLE IF NOT EXISTS arr_monitoring_samples (\n id INTEGER PRIMARY KEY AUTOINCREMENT,\n server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,\n checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n online INTEGER NOT NULL,\n latency_ms INTEGER,\n queue_count INTEGER,\n health_count INTEGER\n);\nCREATE INDEX IF NOT EXISTS idx_arr_monitoring_server_time ON arr_monitoring_samples(server_id, checked_at);\n'


def collect_arr_sample(db, server, base_url, online):
    queue = health = latency = None
    if online:
        http = server_http_session(server)
        try:
            headers = {"X-Api-Key": server.get("token"), "Accept": "application/json"}
            started = time.monotonic()
            response = http.get(base_url.rstrip("/") + "/api/v3/queue?page=1&pageSize=1",
                                headers=headers, timeout=5, allow_redirects=False)
            latency = round((time.monotonic() - started) * 1000)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and type(data.get("totalRecords")) is int:
                    queue = max(0, data["totalRecords"])
            response = http.get(base_url.rstrip("/") + "/api/v3/health", headers=headers,
                                timeout=5, allow_redirects=False)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    health = len(data)
        except Exception:
            pass  # Missing metrics remain null, never a fabricated zero.
        finally:
            http.close()
    db.execute("""INSERT INTO arr_monitoring_samples
        (server_id, online, latency_ms, queue_count, health_count) VALUES (?,?,?,?,?)""",
        (server["id"], int(online), latency, queue, health))
    db.execute("DELETE FROM arr_monitoring_samples WHERE checked_at < datetime('now', '-366 days')")


def load_arr_monitoring(db, servers, requested_range):
    if not servers:
        return {"servers": [], "days": []}
    delta = {"7d":"-7 days", "1m":"-1 month", "6m":"-6 months", "12m":"-12 months", "all":"-366 days"}.get(requested_range, "-7 days")
    summaries = [dict(row) for row in (db.query("""SELECT a.server_id,
        COUNT(*) AS checks, ROUND(100.0 * AVG(a.online), 1) AS availability,
        ROUND(AVG(a.latency_ms)) AS latency_ms
        FROM arr_monitoring_samples a JOIN servers s ON s.id=a.server_id
        WHERE s.type IN ('sonarr','radarr') AND a.checked_at >= datetime('now', ?)
        GROUP BY a.server_id""", (delta,)) or [])]
    by_id = {r["server_id"]:r for r in summaries}
    result = []
    for server in servers:
        row = dict(server)
        row.update(by_id.get(server["id"], {}))
        latest = db.query_one("""SELECT queue_count,health_count FROM arr_monitoring_samples
            WHERE server_id=? ORDER BY checked_at DESC,id DESC LIMIT 1""", (server["id"],))
        row.update(dict(latest) if latest else {})
        result.append(row)
    days = [dict(r) for r in (db.query("""SELECT a.server_id,date(a.checked_at) AS day,
        ROUND(100.0*AVG(a.online),1) AS availability, ROUND(AVG(a.latency_ms)) AS latency_ms,
        ROUND(AVG(a.queue_count),1) AS queue_count, MAX(a.health_count) AS health_count
        FROM arr_monitoring_samples a JOIN servers s ON s.id=a.server_id
        WHERE s.type IN ('sonarr','radarr') AND a.checked_at >= datetime('now', ?)
        GROUP BY a.server_id,date(a.checked_at) ORDER BY day""", (delta,)) or [])]
    return {"servers":result,"days":days}
