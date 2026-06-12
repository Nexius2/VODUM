"""Validate reusable migration plans and learned library mappings."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.migrations.analysis import analyze_migration, is_server_online  # noqa: E402
from core.migrations.drafts import create_migration_draft  # noqa: E402
from core.migrations.phase4 import export_migration_plan, import_migration_plan  # noqa: E402


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
        CREATE TABLE servers(id INTEGER PRIMARY KEY, name TEXT, type TEXT, status TEXT, server_identifier TEXT, last_checked TEXT);
        CREATE TABLE vodum_users(id INTEGER PRIMARY KEY, username TEXT, email TEXT, status TEXT, expiration_date TEXT);
        CREATE TABLE media_users(id INTEGER PRIMARY KEY, server_id INTEGER, vodum_user_id INTEGER, username TEXT, email TEXT, external_user_id TEXT, role TEXT, type TEXT);
        CREATE TABLE libraries(id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT, type TEXT, section_id TEXT);
        CREATE TABLE media_user_libraries(media_user_id INTEGER, library_id INTEGER);
        CREATE TABLE migration_campaigns(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, source_server_id INTEGER, destination_server_id INTEGER,
          migration_type TEXT, migration_mode TEXT, intent TEXT, status TEXT, options_json TEXT,
          library_mapping_json TEXT, analysis_json TEXT, scheduled_at TEXT, batch_size INTEGER, updated_at TEXT
        );
        CREATE TABLE migration_users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, vodum_user_id INTEGER,
          source_media_user_id INTEGER, status TEXT, eligibility TEXT, blockers_json TEXT, source_snapshot_json TEXT
        );
        CREATE TABLE migration_library_mappings(
          id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, source_library_id INTEGER,
          destination_library_id INTEGER, mapping_status TEXT
        );
        CREATE TABLE migration_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT, migration_user_id INTEGER, step_key TEXT
        );
        INSERT INTO servers VALUES(1,'Source Jellyfin','jellyfin','up','jf-source',NULL);
        INSERT INTO servers VALUES(2,'Destination Jellyfin','jellyfin','up','jf-destination',NULL);
        INSERT INTO vodum_users VALUES(10,'alice','alice@example.com','active',NULL);
        INSERT INTO media_users VALUES(100,1,10,'alice','alice@example.com','alice-source','user','jellyfin');
        INSERT INTO libraries VALUES(11,1,'Cinema','movie','source-cinema');
        INSERT INTO libraries VALUES(21,2,'Films','movie','destination-films');
        INSERT INTO media_user_libraries VALUES(100,11);
        """
    )

    assert is_server_online("up")
    assert is_server_online(" online ")
    assert not is_server_online("down")

    campaign_id = create_migration_draft(
        db,
        name="Reusable plan",
        source_server_id=1,
        destination_server_id=2,
        mapping_overrides={11: 21},
        intent="progressive",
        safety_delay_days=5,
        batch_size=20,
    )
    learned = analyze_migration(db, 1, 2)
    mapping = learned["library_mappings"][0]
    assert mapping["suggested_destination"]["id"] == 21
    assert mapping["suggestion_reason"] == "learned"
    policy_statuses = {item["policy"]: item["status"] for item in learned["policy_compatibility"]}
    assert policy_statuses["library_access"] == "supported"
    assert policy_statuses["vodum_stream_policies"] == "preserved"

    plan = export_migration_plan(db, campaign_id)
    serialized = json.dumps(plan)
    assert plan["format"] == "vodum-migration-plan"
    assert plan["source"]["server_identifier"] == "jf-source"
    assert plan["library_mappings"][0]["destination"]["section_id"] == "destination-films"
    assert "token" not in serialized.lower()
    assert "password" not in serialized.lower()

    imported_id = import_migration_plan(db, plan, name_override="Imported reusable plan")
    imported = db.query_one("SELECT name,intent,batch_size,options_json FROM migration_campaigns WHERE id=?", (imported_id,))
    assert imported["name"] == "Imported reusable plan"
    assert imported["intent"] == "progressive"
    assert imported["batch_size"] == 20
    assert json.loads(imported["options_json"])["safety_delay_days"] == 5

    print("OK - Phase 4 accepts up servers, learns mappings and imports/exports secret-free plans.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
