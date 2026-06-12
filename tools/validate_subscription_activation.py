"""Validate deferred subscription activation on first observed playback."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.subscription_activation import activate_subscription_on_playback  # noqa: E402


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
        CREATE TABLE settings(id INTEGER PRIMARY KEY, default_subscription_days INTEGER);
        CREATE TABLE vodum_users(id INTEGER PRIMARY KEY, expiration_date TEXT);
        CREATE TABLE media_users(id INTEGER PRIMARY KEY, vodum_user_id INTEGER);
        INSERT INTO settings VALUES(1, 30);
        INSERT INTO vodum_users VALUES(1, NULL);
        INSERT INTO media_users VALUES(10, 1);
        """
    )
    assert activate_subscription_on_playback(db, 10) is True
    expiration = db.query_one("SELECT expiration_date FROM vodum_users WHERE id=1")["expiration_date"]
    assert expiration and activate_subscription_on_playback(db, 10) is False
    assert db.query_one("SELECT expiration_date FROM vodum_users WHERE id=1")["expiration_date"] == expiration

    plex = (ROOT / "app" / "tasks" / "sync_plex.py").read_text(encoding="utf-8")
    jellyfin = (ROOT / "app" / "tasks" / "sync_jellyfin.py").read_text(encoding="utf-8")
    assert plex.count("ensure_expiration_date_on_first_access") == 1
    assert jellyfin.count("ensure_expiration_date_on_first_access") == 1
    print("OK - subscription expiration starts on first playback, not on library access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
