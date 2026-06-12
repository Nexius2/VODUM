"""Validate explicit source-access removal and rollback."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.migrations import phase3  # noqa: E402


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql, params=(), *, commit=True):
        cursor = self.conn.execute(sql, params)
        if commit:
            self.conn.commit()
        return cursor

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


def main() -> int:
    db = TestDB()
    db.conn.executescript(
        """
        CREATE TABLE servers(id INTEGER PRIMARY KEY, type TEXT, status TEXT);
        CREATE TABLE libraries(id INTEGER PRIMARY KEY, server_id INTEGER);
        CREATE TABLE media_users(id INTEGER PRIMARY KEY, server_id INTEGER, vodum_user_id INTEGER);
        CREATE TABLE media_user_libraries(media_user_id INTEGER, library_id INTEGER, UNIQUE(media_user_id,library_id));
        CREATE TABLE media_sessions(media_user_id INTEGER, last_seen_at TEXT);
        CREATE TABLE media_events(media_user_id INTEGER, ts TEXT);
        CREATE TABLE media_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT, status TEXT, last_error TEXT, processed_at TEXT);
        CREATE TABLE migration_campaigns(id INTEGER PRIMARY KEY, source_server_id INTEGER, intent TEXT, options_json TEXT);
        CREATE TABLE migration_users(
          id INTEGER PRIMARY KEY, campaign_id INTEGER, vodum_user_id INTEGER, status TEXT,
          destination_media_user_id INTEGER, result_json TEXT, source_snapshot_json TEXT,
          updated_at TEXT, completed_at TEXT
        );
        INSERT INTO servers VALUES(1,'plex','online');
        INSERT INTO libraries VALUES(10,1);
        INSERT INTO libraries VALUES(11,1);
        INSERT INTO media_users VALUES(100,1,20);
        INSERT INTO media_users VALUES(101,1,21);
        INSERT INTO media_user_libraries VALUES(100,10);
        INSERT INTO media_user_libraries VALUES(100,11);
        INSERT INTO media_user_libraries VALUES(101,10);
        INSERT INTO media_users VALUES(200,2,22);
        INSERT INTO migration_campaigns VALUES(5,1,'progressive','{"safety_delay_days":7}');
        INSERT INTO migration_users VALUES(50,5,20,'completed',NULL,'{"destination_validated_at":"2026-01-01"}','{}',NULL,NULL);
        INSERT INTO migration_users VALUES(51,5,21,'completed',NULL,'{}','{}',NULL,NULL);
        INSERT INTO migration_users VALUES(52,5,22,'waiting_validation',200,'{"destination_created_at":"2026-01-01 00:00:00"}','{}',NULL,NULL);
        INSERT INTO media_events VALUES(200,CURRENT_TIMESTAMP);
        """
    )
    jobs = []
    phase3.insert_plex_media_job = lambda **kwargs: jobs.append(kwargs) or True
    phase3.insert_jellyfin_media_job = lambda **kwargs: jobs.append(kwargs) or True

    removed = phase3.remove_validated_source_access(db, 5)
    assert removed == {"removed": 1, "queued": 1, "skipped": 1}
    assert db.query_one("SELECT COUNT(*) AS c FROM media_user_libraries WHERE media_user_id=100")["c"] == 0
    assert db.query_one("SELECT COUNT(*) AS c FROM media_user_libraries WHERE media_user_id=101")["c"] == 1
    snapshot = json.loads(db.query_one("SELECT source_snapshot_json FROM migration_users WHERE id=50")["source_snapshot_json"])
    assert snapshot["source_access"] == {"100": [10, 11]}
    assert jobs[0]["action"] == "revoke"
    removal_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=50")["result_json"])
    assert removal_result["source_removal_job_status"] == "queued"
    assert "source_removed_at" not in removal_result
    db.execute(
        "INSERT INTO media_jobs(dedupe_key,status,last_error,processed_at) VALUES(?,?,?,?)",
        (removal_result["source_removal_job_key"], "success", None, "2026-06-11 12:00:00"),
    )
    assert phase3.reconcile_source_jobs(db) == 1
    applied_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=50")["result_json"])
    assert applied_result["source_removed_at"] == "2026-06-11 12:00:00"

    assert phase3.remove_validated_source_access(db, 5) == {"removed": 0, "queued": 0, "skipped": 2}

    restored = phase3.rollback_source_access(db, 5)
    assert restored == {"restored": 1, "queued": 1, "skipped": 2}
    assert db.query_one("SELECT COUNT(*) AS c FROM media_user_libraries WHERE media_user_id=100")["c"] == 2
    assert jobs[1]["action"] == "sync"
    assert phase3.reconcile_destination_usage(db) == 1
    assert db.query_one("SELECT status FROM migration_users WHERE id=52")["status"] == "completed"

    db.execute("UPDATE servers SET status='offline' WHERE id=1")
    try:
        phase3.remove_validated_source_access(db, 5)
        raise AssertionError("Offline source should block Phase 3")
    except ValueError as exc:
        assert "online" in str(exc)

    db.execute("UPDATE servers SET status='online' WHERE id=1")
    db.execute("UPDATE migration_campaigns SET intent='copy' WHERE id=5")
    try:
        phase3.remove_validated_source_access(db, 5)
        raise AssertionError("Copy migrations must never remove source access")
    except ValueError as exc:
        assert "never remove" in str(exc)

    print("OK - Phase 3 removes only validated source access and restores it from snapshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
