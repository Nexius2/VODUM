"""Fast validation of library/media association, grouping and artwork rules."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

# The validation only inspects canonical refs; URL generation is not needed.
if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.url_for = lambda endpoint, **values: (endpoint, values)
    sys.modules["flask"] = flask_stub

from core.monitoring.artwork import extract_artwork_refs  # noqa: E402
from core.monitoring.library_media import (  # noqa: E402
    jellyfin_library_section_id,
    repair_unambiguous_library_associations,
    stable_media_group_key,
    stable_play_key,
)


class TestDB:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


def _validate_repair_and_large_top(stress_rows: int) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE libraries(server_id INTEGER, section_id TEXT, type TEXT);
        CREATE TABLE media_sessions(
          server_id INTEGER, media_type TEXT, library_section_id TEXT
        );
        CREATE TABLE media_session_history(
          id INTEGER PRIMARY KEY, server_id INTEGER, session_key TEXT,
          media_user_id INTEGER, external_user_id TEXT, media_type TEXT,
          media_key TEXT, started_at TEXT, stopped_at TEXT, client_name TEXT,
          library_section_id TEXT
        );
        CREATE INDEX idx_history_library_top_played
        ON media_session_history(server_id, library_section_id, media_key, started_at, stopped_at);
        INSERT INTO libraries VALUES(1, 'movies', 'movie');
        INSERT INTO libraries VALUES(1, 'shows', 'show');
        INSERT INTO media_sessions VALUES(1, 'movie', NULL);
        INSERT INTO media_session_history(
          server_id, session_key, media_user_id, media_type, media_key,
          started_at, stopped_at, client_name, library_section_id
        ) VALUES(1, 'existing', 1, 'movie', 'movie-0',
          '2026-06-10 12:00:01', '2026-06-10 12:10:01', 'TV', NULL);
        """
    )
    repaired = repair_unambiguous_library_associations(TestDB(conn), 1)
    assert repaired == {"live": 1, "history": 1}

    rows = []
    for index in range(stress_rows):
        second = index % 60
        rows.append(
            (
                1,
                f"session-{index}",
                index % 500,
                "movie",
                f"movie-{index % 100}",
                f"2026-06-10 13:{(index // 60) % 60:02d}:{second:02d}",
                f"2026-06-10 14:{(index // 60) % 60:02d}:{second:02d}",
                "TV",
                "movies",
            )
        )
    conn.executemany(
        """
        INSERT INTO media_session_history(
          server_id, session_key, media_user_id, media_type, media_key,
          started_at, stopped_at, client_name, library_section_id
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    count = conn.execute(
        """
        WITH ranked AS (
          SELECT id, ROW_NUMBER() OVER (
            PARTITION BY server_id, session_key, started_at
            ORDER BY stopped_at DESC, id DESC
          ) AS rn
          FROM media_session_history
          WHERE server_id=1 AND library_section_id='movies'
        )
        SELECT COUNT(*) FROM ranked WHERE rn=1
        """
    ).fetchone()[0]
    assert count == stress_rows + 1
    plan = " ".join(
        str(value)
        for row in conn.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT media_key, COUNT(*)
            FROM media_session_history
            WHERE server_id=1 AND library_section_id='movies'
            GROUP BY media_key
            """
        )
        for value in row
    )
    assert "idx_history_library_top_played" in plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stress-rows", type=int, default=20_000)
    args = parser.parse_args()
    assert jellyfin_library_section_id(
        {"CollectionFolderId": "movies-lib", "ParentId": "season-id"}, {}, []
    ) == "movies-lib"
    assert jellyfin_library_section_id(
        {"ParentId": "season-id"},
        {},
        [{"Id": "tv-lib", "Type": "CollectionFolder", "CollectionType": "tvshows"}],
    ) == "tv-lib"

    plex_episode = {
        "server_id": 1,
        "provider": "plex",
        "media_type": "serie",
        "media_key": "episode-1",
        "grandparent_title": "Example",
        "raw_json": json.dumps(
            {
                "VideoOrTrack": {
                    "grandparentRatingKey": "series-42",
                    "grandparentThumb": "/series/42/thumb",
                    "grandparentArt": "/series/42/art",
                }
            }
        ),
    }
    plex_episode_2 = dict(plex_episode, media_key="episode-2")
    same_title_other_series = dict(
        plex_episode,
        raw_json=json.dumps({"VideoOrTrack": {"grandparentRatingKey": "series-99"}}),
    )
    assert stable_media_group_key(plex_episode) == stable_media_group_key(plex_episode_2)
    assert stable_media_group_key(plex_episode) != stable_media_group_key(same_title_other_series)

    refs = extract_artwork_refs(plex_episode)
    assert refs["poster_ref"]["path"] == "/series/42/thumb"
    assert refs["backdrop_ref"]["path"] == "/series/42/art"
    assert refs["poster_ref"]["target_id"] == "series-42"

    jellyfin_episode = {
        "server_id": 2,
        "provider": "jellyfin",
        "media_type": "episode",
        "media_key": "episode-jf",
        "raw_json": json.dumps({"NowPlayingItem": {"Id": "episode-jf", "SeriesId": "series-jf"}}),
    }
    jf_refs = extract_artwork_refs(jellyfin_episode)
    assert jf_refs["poster_ref"]["item_id"] == "series-jf"

    first_play = {
        "server_id": 1,
        "media_user_id": 5,
        "media_key": "movie-1",
        "started_at": "2026-06-10 12:00:01",
        "client_name": "TV",
    }
    second_play = dict(first_play, started_at="2026-06-10 12:00:48")
    assert stable_play_key(first_play) != stable_play_key(second_play)
    session_snapshot = dict(first_play, session_key="native-session")
    assert stable_play_key(session_snapshot) == stable_play_key(dict(session_snapshot))

    _validate_repair_and_large_top(max(1, args.stress_rows))

    print(
        "OK - library association, stable Top played identities, canonical series artwork "
        f"and indexed stress dataset ({max(1, args.stress_rows)} rows) validated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
