import sys
import time
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.aggregate_cache import cached_aggregate, clear_aggregate_cache  # noqa: E402


clear_aggregate_cache()
calls = {"count": 0}


def loader():
    calls["count"] += 1
    return {"rows": [{"value": calls["count"]}]}


first = cached_aggregate("validation", 1, loader)
first["rows"][0]["value"] = 999
second = cached_aggregate("validation", 1, loader)

assert calls["count"] == 1
assert second["rows"][0]["value"] == 1

time.sleep(1.05)
third = cached_aggregate("validation", 1, loader)
assert calls["count"] == 2
assert third["rows"][0]["value"] == 2

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE sample(value INTEGER)")
conn.execute("INSERT INTO sample(value) VALUES(7)")
sqlite_rows = cached_aggregate(
    "sqlite-rows",
    60,
    lambda: [dict(row) for row in conn.execute("SELECT value FROM sample")],
)
assert sqlite_rows == [{"value": 7}]

dashboard = (ROOT / "app" / "routes" / "dashboard.py").read_text(encoding="utf-8")
assert '"dashboard:usage-risk:30d"' in dashboard
assert '"dashboard:server-peaks:7d"' in dashboard

monitoring_route = (ROOT / "app" / "routes" / "monitoring_overview.py").read_text(encoding="utf-8")
monitoring_service = (
    ROOT / "app" / "core" / "monitoring" / "overview_aggregates.py"
).read_text(encoding="utf-8")
for cache_key in (
    '"monitoring:overview:stats-7d"',
    '"monitoring:overview:top-users-30d"',
    '"monitoring:overview:concurrent-7d"',
    '"monitoring:overview:top-series-30d"',
    '"monitoring:overview:top-movies-30d"',
):
    assert cache_key in monitoring_service
    assert cache_key not in monitoring_route
assert "build_monitoring_overview_aggregates(db, sessions_stats)" in monitoring_route

print("OK - expensive dashboard and monitoring aggregates use a bounded defensive TTL cache.")
