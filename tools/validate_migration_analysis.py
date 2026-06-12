"""Validate the read-only multi-provider migration analysis."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.migrations.analysis import analyze_migration, is_server_online, migration_pair_blocker, migration_workspace_blocker  # noqa: E402
from core.migrations.drafts import create_migration_draft, delete_migration_draft, update_migration_draft  # noqa: E402


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


def create_schema(db: TestDB) -> None:
    db.conn.executescript(
        """
        CREATE TABLE servers(
          id INTEGER PRIMARY KEY, name TEXT, type TEXT, status TEXT,
          server_identifier TEXT, last_checked TEXT
        );
        CREATE TABLE vodum_users(
          id INTEGER PRIMARY KEY, username TEXT, email TEXT, status TEXT,
          expiration_date TEXT
        );
        CREATE TABLE media_users(
          id INTEGER PRIMARY KEY, server_id INTEGER, vodum_user_id INTEGER,
          username TEXT, email TEXT, external_user_id TEXT, role TEXT, type TEXT
        );
        CREATE TABLE libraries(
          id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT, type TEXT,
          section_id TEXT
        );
        CREATE TABLE media_user_libraries(media_user_id INTEGER, library_id INTEGER);
        CREATE TABLE migration_campaigns(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, source_server_id INTEGER,
          destination_server_id INTEGER, migration_type TEXT, migration_mode TEXT,
          intent TEXT, status TEXT, options_json TEXT, library_mapping_json TEXT, analysis_json TEXT
          , scheduled_at TEXT, batch_size INTEGER, updated_at TEXT
        );
        CREATE TABLE migration_users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, vodum_user_id INTEGER,
          source_media_user_id INTEGER, status TEXT, eligibility TEXT, blockers_json TEXT,
          source_snapshot_json TEXT
        );
        CREATE TABLE migration_library_mappings(
          id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, source_library_id INTEGER,
          destination_library_id INTEGER, mapping_status TEXT
        );
        CREATE TABLE migration_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT, migration_user_id INTEGER, step_key TEXT
        );
        """
    )


def seed(db: TestDB) -> None:
    db.conn.executescript(
        """
        INSERT INTO servers VALUES(1, 'Plex A', 'plex', 'online', 'p-a', NULL);
        INSERT INTO servers VALUES(2, 'Plex B', 'plex', 'online', 'p-b', NULL);
        INSERT INTO servers VALUES(3, 'Jellyfin A', 'jellyfin', 'online', 'j-a', NULL);
        INSERT INTO servers VALUES(4, 'Jellyfin B', 'jellyfin', 'online', 'j-b', NULL);

        INSERT INTO vodum_users VALUES(10, 'alice', 'alice@example.com', 'active', NULL);
        INSERT INTO vodum_users VALUES(11, 'bob', NULL, 'active', NULL);
        INSERT INTO vodum_users VALUES(12, 'carol', 'carol@example.com', 'active', NULL);

        INSERT INTO media_users VALUES(100, 1, 10, 'alice', 'alice@example.com', 'plex-a', 'friend', 'plex');
        INSERT INTO media_users VALUES(101, 1, 12, 'carol', 'carol@example.com', 'plex-c', 'friend', 'plex');
        INSERT INTO media_users VALUES(102, 1, NULL, 'owner-a', 'owner@example.com', 'owner-1', 'owner', 'plex');
        INSERT INTO media_users VALUES(103, 2, NULL, 'owner-b', 'owner-b@example.com', 'owner-2', 'owner', 'plex');
        INSERT INTO media_users VALUES(110, 3, 11, 'bob', NULL, 'jf-bob', 'user', 'jellyfin');
        INSERT INTO media_users VALUES(111, 3, 12, 'carol', 'carol@example.com', 'jf-carol', 'user', 'jellyfin');
        INSERT INTO media_users VALUES(120, 4, 10, 'alice', 'alice@example.com', 'jf-alice', 'user', 'jellyfin');

        INSERT INTO libraries VALUES(1, 1, 'Movies', 'movie', '1');
        INSERT INTO libraries VALUES(2, 1, 'Rare Shows', 'show', '2');
        INSERT INTO libraries VALUES(3, 2, 'Movies', 'movie', '3');
        INSERT INTO libraries VALUES(4, 3, 'Movies', 'movie', '4');
        INSERT INTO libraries VALUES(5, 4, 'Movies', 'movie', '5');
        INSERT INTO libraries VALUES(6, 1, 'Unused', 'show', '6');

        INSERT INTO media_user_libraries VALUES(100, 1);
        INSERT INTO media_user_libraries VALUES(101, 2);
        INSERT INTO media_user_libraries VALUES(110, 4);
        INSERT INTO media_user_libraries VALUES(111, 4);
        """
    )


def main() -> int:
    db = TestDB()
    create_schema(db)
    seed(db)
    assert is_server_online("up")
    assert is_server_online(" online ")
    assert not is_server_online("down")

    plex_to_plex = analyze_migration(db, 1, 2)
    assert plex_to_plex["mode"] == "invite"
    assert plex_to_plex["requires_email"] is True
    assert plex_to_plex["counts"] == {
        "total": 2,
        "ready": 1,
        "blocked": 1,
        "already_present": 0,
        "unmapped_libraries": 1,
    }
    unused_mapping = next(item for item in plex_to_plex["library_mappings"] if item["source"]["id"] == 6)
    assert unused_mapping["status"] == "unused"
    servers = [dict(row) for row in db.query("SELECT id, type FROM servers ORDER BY id")]
    assert migration_workspace_blocker(db, servers) == ""
    assert migration_workspace_blocker(db, servers[:1]) == "single_server"
    assert migration_workspace_blocker(db, servers[:2]) == ""

    mapped_plex = analyze_migration(db, 1, 2, {2: 3})
    assert mapped_plex["counts"]["blocked"] == 0
    assert mapped_plex["counts"]["ready"] == 2

    jellyfin_to_plex = analyze_migration(db, 3, 2)
    bob = next(user for user in jellyfin_to_plex["users"] if user["username"] == "bob")
    assert jellyfin_to_plex["mode"] == "invite"
    assert "needs_email" in bob["reasons"]

    jellyfin_to_jellyfin = analyze_migration(db, 3, 4)
    carol = next(user for user in jellyfin_to_jellyfin["users"] if user["username"] == "carol")
    assert jellyfin_to_jellyfin["mode"] == "create_local"
    assert carol["classification"] == "ready"

    plex_to_jellyfin = analyze_migration(db, 1, 4)
    alice = next(user for user in plex_to_jellyfin["users"] if user["username"] == "alice")
    assert alice["classification"] == "already_present"

    db.execute("UPDATE vodum_users SET username='' WHERE id=10")
    db.execute("UPDATE media_users SET username='' WHERE id=100")
    db.execute("DELETE FROM media_users WHERE id=120")
    missing_username = analyze_migration(db, 1, 4)
    alice_missing_username = next(user for user in missing_username["users"] if user["vodum_user_id"] == 10)
    assert alice_missing_username["classification"] == "blocked"
    assert "needs_username" in alice_missing_username["reasons"]
    db.execute("UPDATE vodum_users SET username='alice' WHERE id=10")
    db.execute("UPDATE media_users SET username='alice' WHERE id=100")
    db.execute("INSERT INTO media_users VALUES(120, 4, 10, 'alice', 'alice@example.com', 'jf-alice', 'user', 'jellyfin')")

    db.execute("UPDATE media_users SET external_user_id='' WHERE id=120")
    invalid_existing = analyze_migration(db, 1, 4)
    invalid_alice = next(user for user in invalid_existing["users"] if user["vodum_user_id"] == 10)
    assert invalid_alice["classification"] == "blocked"
    assert "destination_identity_missing" in invalid_alice["reasons"]
    db.execute("UPDATE media_users SET external_user_id='jf-alice' WHERE id=120")

    existing_unmapped = analyze_migration(db, 1, 4, {1: None})
    existing_alice = next(user for user in existing_unmapped["users"] if user["vodum_user_id"] == 10)
    assert existing_alice["classification"] == "blocked"
    assert "needs_library_mapping" in existing_alice["reasons"]

    db.execute("INSERT INTO vodum_users VALUES(13, 'no-access', 'no-access@example.com', 'expired', NULL)")
    db.execute("INSERT INTO media_users VALUES(112, 3, 13, 'no-access', 'no-access@example.com', 'jf-no-access', 'user', 'jellyfin')")
    no_access_analysis = analyze_migration(db, 3, 4)
    no_access = next(user for user in no_access_analysis["users"] if user["username"] == "no-access")
    assert no_access["reasons"] == ["no_source_access"]
    assert no_access["classification"] == "excluded"
    db.execute("DELETE FROM media_users WHERE id=112")
    db.execute("DELETE FROM vodum_users WHERE id=13")

    for source_id, destination_id, expected_reason in [
        (1, 1, "same_server"),
    ]:
        try:
            analyze_migration(db, source_id, destination_id)
            raise AssertionError(f"{expected_reason} pair should be rejected")
        except ValueError as exc:
            assert expected_reason in str(exc)

    db.execute("UPDATE servers SET status='offline' WHERE id=4")
    try:
        analyze_migration(db, 3, 4)
        raise AssertionError("Offline destination should be rejected")
    except ValueError as exc:
        assert "server_offline" in str(exc)
    db.execute("UPDATE servers SET status='online' WHERE id=4")

    db.execute("UPDATE servers SET server_identifier='j-a' WHERE id=4")
    try:
        analyze_migration(db, 3, 4)
        raise AssertionError("Duplicate native server should be rejected")
    except ValueError as exc:
        assert "same_server" in str(exc)
    db.execute("UPDATE servers SET server_identifier='j-b' WHERE id=4")

    db.execute("UPDATE media_users SET external_user_id='owner-1' WHERE id=103")
    assert migration_workspace_blocker(db, servers[:2]) == "shared_plex_account"
    try:
        analyze_migration(db, 1, 2)
        raise AssertionError("Shared-owner Plex analysis should be rejected")
    except ValueError as exc:
        assert "shared_plex_pair" in str(exc)
    try:
        create_migration_draft(
            db,
            name="Invalid shared Plex draft",
            source_server_id=1,
            destination_server_id=2,
            mapping_overrides={1: 3, 2: 3},
        )
        raise AssertionError("Shared-owner Plex draft should be rejected")
    except ValueError:
        pass
    db.execute("UPDATE media_users SET external_user_id='owner-2' WHERE id=103")

    campaign_id = create_migration_draft(
        db,
        name="Validated draft",
        source_server_id=3,
        destination_server_id=4,
        mapping_overrides={4: 5},
    )
    assert db.query_one(
        "SELECT status FROM migration_campaigns WHERE id = ?",
        (campaign_id,),
    )["status"] == "draft"
    assert db.query_one(
        "SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id = ?",
        (campaign_id,),
    )["total"] == 2
    assert db.query_one(
        "SELECT COUNT(*) AS total FROM migration_library_mappings WHERE campaign_id = ?",
        (campaign_id,),
    )["total"] == 1
    snapshots = [
        json.loads(row["source_snapshot_json"])
        for row in db.query("SELECT source_snapshot_json FROM migration_users WHERE campaign_id=?", (campaign_id,))
    ]
    assert any(snapshot.get("source_access") == {"110": [4]} for snapshot in snapshots)

    update_migration_draft(
        db,
        campaign_id,
        name="Edited draft",
        mapping_overrides={4: None},
        safety_delay_days=12,
        batch_size=25,
        intent="progressive",
    )
    edited = db.query_one("SELECT name,intent,batch_size,options_json FROM migration_campaigns WHERE id=?", (campaign_id,))
    assert edited["name"] == "Edited draft"
    assert edited["intent"] == "progressive"
    assert edited["batch_size"] == 25
    assert json.loads(edited["options_json"])["safety_delay_days"] == 12
    assert db.query_one("SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id=? AND eligibility='blocked'", (campaign_id,))["total"] == 2

    update_migration_draft(
        db,
        campaign_id,
        name="Edited draft",
        mapping_overrides={4: 5},
        intent="progressive",
    )
    assert db.query_one("SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id=? AND eligibility='blocked'", (campaign_id,))["total"] == 0

    protected_id = create_migration_draft(
        db,
        name="Protected after start",
        source_server_id=3,
        destination_server_id=4,
        mapping_overrides={4: 5},
    )
    db.execute("UPDATE migration_campaigns SET status='running' WHERE id=?", (protected_id,))
    for operation in (
        lambda: delete_migration_draft(db, protected_id),
        lambda: update_migration_draft(db, protected_id, name="no", mapping_overrides={4: 5}),
    ):
        try:
            operation()
            raise AssertionError("Started campaigns must be immutable from draft actions")
        except ValueError:
            pass

    delete_migration_draft(db, campaign_id)
    assert db.query_one("SELECT id FROM migration_campaigns WHERE id=?", (campaign_id,)) is None

    unused_draft_id = create_migration_draft(
        db,
        name="Unused libraries do not block",
        source_server_id=1,
        destination_server_id=2,
        mapping_overrides={1: 3, 2: 3},
    )
    assert db.query_one(
        "SELECT mapping_status FROM migration_library_mappings WHERE campaign_id=? AND source_library_id=6",
        (unused_draft_id,),
    )["mapping_status"] == "unused"

    db.execute("UPDATE servers SET server_identifier='shared-cross-provider' WHERE id IN (1,3)")
    assert migration_pair_blocker(db, 1, 3) == ""

    print("OK - migration dry run, blockers, manual mappings and drafts are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
