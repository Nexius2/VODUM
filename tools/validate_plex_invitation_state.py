"""Validate Plex invitation-state normalization without contacting Plex."""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.providers.plex_invitation_state import (  # noqa: E402
    classify_plex_invite_error,
    merge_accepted_plex_media_user,
    matches_plex_identity,
    plex_invite_state_payload,
)


class PlexObject:
    def __init__(self, **values):
        self.__dict__.update(values)


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)


def main() -> int:
    assert classify_plex_invite_error("User already invited") == "pending"
    assert classify_plex_invite_error("Library request sent") == "pending"
    assert classify_plex_invite_error("This account is already a friend") == "friend"
    assert classify_plex_invite_error("401 Unauthorized") is None

    pending = PlexObject(email="Person@Example.com")
    friend = PlexObject(id=12345, username="PlexName")
    assert matches_plex_identity(pending, email="person@example.com")
    assert matches_plex_identity(friend, external_user_id="12345")
    assert matches_plex_identity(friend, username="plexname")
    assert not matches_plex_identity(friend, email="other@example.com")

    assert plex_invite_state_payload("pending") == {
        "state": "pending",
        "is_friend": False,
        "is_pending": True,
    }
    assert plex_invite_state_payload("friend", primary_server_id=7) == {
        "state": "friend",
        "is_friend": True,
        "is_pending": False,
        "primary_server_id": 7,
    }

    db = TestDB()
    db.conn.executescript(
        """
        CREATE TABLE media_users(id INTEGER PRIMARY KEY);
        CREATE TABLE media_user_libraries(
          media_user_id INTEGER, library_id INTEGER,
          PRIMARY KEY(media_user_id, library_id)
        );
        CREATE TABLE media_sessions(id INTEGER PRIMARY KEY, media_user_id INTEGER);
        CREATE TABLE media_events(id INTEGER PRIMARY KEY, media_user_id INTEGER);
        CREATE TABLE media_session_history(
          id INTEGER PRIMARY KEY, media_user_id INTEGER,
          UNIQUE(media_user_id, id)
        );
        INSERT INTO media_users VALUES(10);
        INSERT INTO media_users VALUES(20);
        INSERT INTO media_user_libraries VALUES(20, 7);
        INSERT INTO media_sessions VALUES(1, 20);
        INSERT INTO media_events VALUES(1, 20);
        INSERT INTO media_session_history VALUES(1, 20);
        """
    )
    assert merge_accepted_plex_media_user(db, accepted_id=10, pending_id=20)
    assert db.conn.execute("SELECT COUNT(*) FROM media_users WHERE id=20").fetchone()[0] == 0
    assert db.conn.execute("SELECT media_user_id FROM media_user_libraries").fetchone()[0] == 10
    assert db.conn.execute("SELECT media_user_id FROM media_sessions").fetchone()[0] == 10
    assert db.conn.execute("SELECT media_user_id FROM media_events").fetchone()[0] == 10
    assert db.conn.execute("SELECT media_user_id FROM media_session_history").fetchone()[0] == 10

    print("OK - Plex invitation states and identities are normalized consistently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
