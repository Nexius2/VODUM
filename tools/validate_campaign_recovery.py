"""Validate campaign recovery after an interrupted worker or application restart."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.communications.campaign_recovery import recover_campaigns  # noqa: E402


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, params)
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
        CREATE TABLE comm_campaigns(
          id INTEGER PRIMARY KEY, status TEXT, is_test INTEGER,
          updated_at TEXT, sent_at TEXT
        );
        CREATE TABLE comm_campaign_targets(
          id INTEGER PRIMARY KEY, campaign_id INTEGER, status TEXT,
          attempt_count INTEGER, max_attempts INTEGER, next_attempt_at TEXT,
          updated_at TEXT
        );

        INSERT INTO comm_campaigns VALUES(1, 'sending', 1, datetime('now','-2 hours'), NULL);
        INSERT INTO comm_campaigns VALUES(2, 'error', 0, CURRENT_TIMESTAMP, NULL);
        INSERT INTO comm_campaigns VALUES(3, 'sending', 0, CURRENT_TIMESTAMP, NULL);
        INSERT INTO comm_campaigns VALUES(4, 'sending', 0, CURRENT_TIMESTAMP, NULL);

        INSERT INTO comm_campaign_targets VALUES(20, 2, 'error', 1, 10, NULL, CURRENT_TIMESTAMP);
        INSERT INTO comm_campaign_targets VALUES(30, 3, 'sent', 1, 10, NULL, CURRENT_TIMESTAMP);
        INSERT INTO comm_campaign_targets VALUES(40, 4, 'error', 10, 10, NULL, CURRENT_TIMESTAMP);
        """
    )

    stats = recover_campaigns(db)
    assert stats == {
        "test_campaigns_requeued": 1,
        "retry_dates_repaired": 1,
        "campaigns_reconciled": 3,
    }
    statuses = {
        row["id"]: row["status"]
        for row in db.query("SELECT id,status FROM comm_campaigns ORDER BY id")
    }
    assert statuses == {1: "pending", 2: "sending", 3: "finished", 4: "error"}
    assert db.query_one("SELECT next_attempt_at FROM comm_campaign_targets WHERE id=20")["next_attempt_at"]

    second = recover_campaigns(db)
    assert second == {
        "test_campaigns_requeued": 0,
        "retry_dates_repaired": 0,
        "campaigns_reconciled": 0,
    }
    assert db.query_one("SELECT status FROM comm_campaign_targets WHERE id=30")["status"] == "sent"

    print("OK - interrupted campaigns recover automatically and recovery is idempotent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
