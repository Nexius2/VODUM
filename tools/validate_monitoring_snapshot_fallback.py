import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.monitoring.snapshots import get_live_session_stats  # noqa: E402


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE media_sessions(last_seen_at TEXT, is_transcode INTEGER);
            CREATE TABLE tasks(name TEXT, status TEXT, queued_count INTEGER);
            CREATE TABLE media_jobs(action TEXT, status TEXT);
            CREATE TABLE monitoring_snapshots(
              id INTEGER PRIMARY KEY, ts TEXT, live_sessions INTEGER, transcodes INTEGER
            );
            """
        )

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


db = DB()
db.conn.execute(
    "INSERT INTO monitoring_snapshots(ts, live_sessions, transcodes) VALUES(CURRENT_TIMESTAMP, 4, 1)"
)

idle = get_live_session_stats(db)
assert idle["live_sessions"] == 0
assert idle["is_snapshot_fallback"] is False

db.conn.execute(
    "INSERT INTO tasks(name, status, queued_count) VALUES('media_jobs_worker', 'running', 0)"
)
fallback = get_live_session_stats(db)
assert fallback["live_sessions"] == 4
assert fallback["transcodes"] == 1
assert fallback["direct_plays"] == 3
assert fallback["is_snapshot_fallback"] is True

db.conn.execute(
    "INSERT INTO media_sessions(last_seen_at, is_transcode) VALUES(CURRENT_TIMESTAMP, 0)"
)
live = get_live_session_stats(db)
assert live["live_sessions"] == 1
assert live["is_snapshot_fallback"] is False

print("OK - monitoring snapshot fallback is recent, explicit and limited to a busy pipeline.")
