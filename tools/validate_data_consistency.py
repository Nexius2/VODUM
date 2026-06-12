"""Validate conservative cleanup of impossible access relationships."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.data_consistency import audit_access_consistency, repair_access_consistency  # noqa: E402


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor


def main() -> int:
    db = TestDB()
    db.conn.executescript(
        """
        CREATE TABLE media_users(id INTEGER PRIMARY KEY, server_id INTEGER);
        CREATE TABLE libraries(id INTEGER PRIMARY KEY, server_id INTEGER);
        CREATE TABLE media_user_libraries(media_user_id INTEGER, library_id INTEGER);
        INSERT INTO media_users VALUES(1, 10);
        INSERT INTO media_users VALUES(2, 20);
        INSERT INTO libraries VALUES(100, 10);
        INSERT INTO libraries VALUES(200, 20);
        INSERT INTO media_user_libraries VALUES(1, 100);
        INSERT INTO media_user_libraries VALUES(1, 200);
        INSERT INTO media_user_libraries VALUES(999, 100);
        INSERT INTO media_user_libraries VALUES(2, 999);
        """
    )
    assert audit_access_consistency(db) == {
        "orphan_media_users": 1,
        "orphan_libraries": 1,
        "cross_server": 1,
    }
    result = repair_access_consistency(db)
    assert result["deleted"] == 3 and result["remaining"] == 0
    assert db.query_one("SELECT COUNT(*) AS count FROM media_user_libraries")["count"] == 1
    print("OK - invalid and cross-server access rows are cleaned conservatively.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
