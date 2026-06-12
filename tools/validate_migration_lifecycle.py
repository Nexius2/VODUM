"""Validate migration pause, resume, retry, exclusion and concurrency controls."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.migrations.lifecycle import (  # noqa: E402
    conflicting_active_users,
    pause_campaign,
    resume_campaign,
    retry_failed_users,
    set_user_excluded,
)


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
        CREATE TABLE migration_campaigns(
          id INTEGER PRIMARY KEY, name TEXT, destination_server_id INTEGER, status TEXT,
          scheduled_at TEXT, started_at TEXT, completed_at TEXT, updated_at TEXT
        );
        CREATE TABLE migration_users(
          id INTEGER PRIMARY KEY, campaign_id INTEGER, vodum_user_id INTEGER, status TEXT,
          eligibility TEXT, blockers_json TEXT, options_json TEXT, last_error TEXT, updated_at TEXT
        );
        INSERT INTO migration_campaigns VALUES(1,'Main',20,'running',NULL,NULL,NULL,NULL);
        INSERT INTO migration_campaigns VALUES(2,'Conflict',20,'running',NULL,NULL,NULL,NULL);
        INSERT INTO migration_users VALUES(10,1,100,'failed','ready','[]','{}','temporary',NULL);
        INSERT INTO migration_users VALUES(11,1,101,'pending','ready','[]','{}',NULL,NULL);
        INSERT INTO migration_users VALUES(20,2,101,'pending','ready','[]','{}',NULL,NULL);
        INSERT INTO migration_users VALUES(12,1,102,'failed','already_present','["destination_account_exists"]','{}','temporary',NULL);
        """
    )
    assert len(conflicting_active_users(db, 1)) == 1
    db.execute("UPDATE migration_campaigns SET status='completed' WHERE id=2")
    assert conflicting_active_users(db, 1) == []

    pause_campaign(db, 1)
    assert db.query_one("SELECT status FROM migration_campaigns WHERE id=1")["status"] == "paused"
    resume_campaign(db, 1)
    assert db.query_one("SELECT status FROM migration_campaigns WHERE id=1")["status"] == "running"

    assert retry_failed_users(db, 1) == 2
    assert db.query_one("SELECT status FROM migration_users WHERE id=10")["status"] == "pending"
    assert db.query_one("SELECT status FROM migration_users WHERE id=12")["status"] == "pending"

    set_user_excluded(db, 1, 11, True)
    excluded = db.query_one("SELECT status,eligibility FROM migration_users WHERE id=11")
    assert excluded["status"] == "excluded" and excluded["eligibility"] == "excluded"
    set_user_excluded(db, 1, 11, False)
    included = db.query_one("SELECT status,eligibility FROM migration_users WHERE id=11")
    assert included["status"] == "pending" and included["eligibility"] == "ready"
    db.execute("UPDATE migration_campaigns SET status='completed' WHERE id=1")
    try:
        set_user_excluded(db, 1, 11, True)
        raise AssertionError("Completed campaigns must be immutable")
    except ValueError:
        pass

    print("OK - migration lifecycle controls preserve progress and block concurrent destinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
