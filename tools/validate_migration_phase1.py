"""Validate destination-only Phase 1 execution without contacting providers."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

provider_jellyfin = types.ModuleType("core.providers.jellyfin_users")
provider_jellyfin.jellyfin_create_user = lambda *args, **kwargs: {}
provider_jellyfin.jellyfin_set_password = lambda *args, **kwargs: None
provider_jellyfin.jellyfin_set_policy_folders = lambda *args, **kwargs: None
sys.modules["core.providers.jellyfin_users"] = provider_jellyfin

provider_plex = types.ModuleType("core.providers.plex_users")
provider_plex.plex_invite_and_share = lambda *args, **kwargs: {}
sys.modules["core.providers.plex_users"] = provider_plex

secret_store = types.ModuleType("secret_store")
secret_store.encrypt_secret = lambda value: f"encrypted:{value}"
sys.modules["secret_store"] = secret_store

communications = types.ModuleType("communications_engine")
communications.select_comm_templates_for_user = lambda **kwargs: []
communications.schedule_template_notification = lambda **kwargs: None
communications.enqueue_named_task = lambda *args, **kwargs: None
sys.modules["communications_engine"] = communications

from core.migrations import execution  # noqa: E402


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
          id INTEGER PRIMARY KEY, name TEXT, type TEXT, status TEXT, token TEXT,
          url TEXT, local_url TEXT, public_url TEXT, settings_json TEXT
        );
        CREATE TABLE vodum_users(id INTEGER PRIMARY KEY, username TEXT, email TEXT, status TEXT);
        CREATE TABLE media_users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, server_id INTEGER, vodum_user_id INTEGER,
          external_user_id TEXT, username TEXT, email TEXT, type TEXT, details_json TEXT,
          accepted_at TEXT
        );
        CREATE TABLE libraries(id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT, section_id TEXT);
        CREATE TABLE media_user_libraries(media_user_id INTEGER, library_id INTEGER, UNIQUE(media_user_id, library_id));
        CREATE TABLE migration_campaigns(
          id INTEGER PRIMARY KEY, source_server_id INTEGER, destination_server_id INTEGER,
          status TEXT, completed_at TEXT, updated_at TEXT
        );
        CREATE TABLE migration_users(
          id INTEGER PRIMARY KEY, campaign_id INTEGER, vodum_user_id INTEGER,
          source_media_user_id INTEGER, destination_media_user_id INTEGER, status TEXT,
          eligibility TEXT, attempts INTEGER DEFAULT 0, last_error TEXT, result_json TEXT,
          started_at TEXT, completed_at TEXT, updated_at TEXT
        );
        CREATE TABLE migration_library_mappings(
          id INTEGER PRIMARY KEY, campaign_id INTEGER, source_library_id INTEGER,
          destination_library_id INTEGER, mapping_status TEXT
        );
        """
    )


def seed(db: TestDB) -> None:
    db.conn.executescript(
        """
        INSERT INTO servers VALUES(1,'Source Plex','plex','online','x','http://p',NULL,NULL,NULL);
        INSERT INTO servers VALUES(2,'Destination Jellyfin','jellyfin','online','x','http://j',NULL,NULL,NULL);
        INSERT INTO servers VALUES(3,'Destination Plex','plex','online','x','http://p2',NULL,NULL,NULL);
        INSERT INTO vodum_users VALUES(10,'alice','alice@example.com','active');
        INSERT INTO vodum_users VALUES(11,'bob','bob@example.com','active');
        INSERT INTO media_users(id,server_id,vodum_user_id,external_user_id,username,email,type)
          VALUES(100,1,10,'pa','alice','alice@example.com','plex');
        INSERT INTO media_users(id,server_id,vodum_user_id,external_user_id,username,email,type)
          VALUES(101,1,11,'pb','bob','bob@example.com','plex');
        INSERT INTO libraries VALUES(1,1,'Movies','s1');
        INSERT INTO libraries VALUES(2,1,'Shows','s2');
        INSERT INTO libraries VALUES(3,2,'Movies','d1');
        INSERT INTO libraries VALUES(4,2,'Shows','d2');
        INSERT INTO libraries VALUES(5,3,'Movies','p1');
        INSERT INTO media_user_libraries VALUES(100,1);
        INSERT INTO media_user_libraries VALUES(101,2);
        INSERT INTO migration_campaigns VALUES(20,1,2,'running',NULL,NULL);
        INSERT INTO migration_users(id,campaign_id,vodum_user_id,source_media_user_id,status,eligibility)
          VALUES(200,20,10,100,'processing','ready');
        INSERT INTO migration_library_mappings VALUES(1,20,1,3,'mapped');
        INSERT INTO migration_library_mappings VALUES(2,20,2,4,'mapped');
        """
    )


def main() -> int:
    db = TestDB()
    create_schema(db)
    seed(db)

    policies = []
    execution.jellyfin_create_user = lambda server, username: {"Id": f"jf-{username}", "Name": username}
    execution.jellyfin_set_password = lambda server, user_id, password: None
    execution.jellyfin_set_policy_folders = lambda server, user_id, folders: policies.append((user_id, folders))
    execution.encrypt_secret = lambda password: f"encrypted:{password}"

    campaign = {
        "id": 20,
        "source_server_id": 1,
        "destination_server_id": 2,
        "destination_type": "jellyfin",
    }
    migration_user = dict(db.query_one("SELECT * FROM migration_users WHERE id=200"))
    assert execution.process_migration_user(db, campaign, migration_user) == "waiting_validation"
    assert policies == [("jf-alice", ["d1"])]
    destination = db.query_one("SELECT id FROM media_users WHERE server_id=2 AND vodum_user_id=10")
    assert destination
    assert db.query_one(
        "SELECT COUNT(*) AS total FROM media_user_libraries WHERE media_user_id=? AND library_id=3",
        (destination["id"],),
    )["total"] == 1
    assert db.query_one(
        "SELECT COUNT(*) AS total FROM media_user_libraries WHERE media_user_id=? AND library_id=4",
        (destination["id"],),
    )["total"] == 0
    assert db.query_one("SELECT COUNT(*) AS total FROM media_user_libraries WHERE media_user_id=100")["total"] == 1
    result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=200")["result_json"])
    assert result["credentials_pending_delivery"] is True
    assert result["encrypted_generated_password"].startswith("encrypted:")
    assert result["credentials_expires_at"]
    migration_user_retry = dict(db.query_one("SELECT * FROM migration_users WHERE id=200"))
    assert execution.process_migration_user(db, campaign, migration_user_retry) == "waiting_validation"
    retry_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=200")["result_json"])
    assert retry_result["encrypted_generated_password"] == result["encrypted_generated_password"]
    assert db.query_one("SELECT COUNT(*) AS total FROM media_users WHERE server_id=2 AND vodum_user_id=10")["total"] == 1
    assert db.query_one("SELECT COUNT(*) AS total FROM media_user_libraries WHERE media_user_id=100")["total"] == 1

    db.execute("INSERT INTO migration_users(id,campaign_id,vodum_user_id,source_media_user_id,status,eligibility) VALUES(202,20,11,101,'processing','ready')")
    original_set_password = execution.jellyfin_set_password
    execution.jellyfin_set_password = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupted"))
    interrupted = dict(db.query_one("SELECT * FROM migration_users WHERE id=202"))
    try:
        execution.process_migration_user(db, campaign, interrupted)
        raise AssertionError("Interrupted password setup should fail")
    except RuntimeError as exc:
        assert str(exc) == "interrupted"
    assert db.query_one("SELECT COUNT(*) AS total FROM media_users WHERE server_id=2 AND vodum_user_id=11")["total"] == 1
    execution.jellyfin_set_password = original_set_password
    interrupted_retry = dict(db.query_one("SELECT * FROM migration_users WHERE id=202"))
    assert execution.process_migration_user(db, campaign, interrupted_retry) == "waiting_validation"
    interrupted_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=202")["result_json"])
    assert interrupted_result["encrypted_generated_password"].startswith("encrypted:")

    db.execute("INSERT INTO migration_campaigns VALUES(21,1,3,'running',NULL,NULL)")
    db.execute(
        "INSERT INTO migration_users(id,campaign_id,vodum_user_id,source_media_user_id,status,eligibility) VALUES(201,21,10,100,'processing','ready')"
    )
    db.execute("INSERT INTO migration_library_mappings VALUES(3,21,1,5,'mapped')")
    plex_calls = []
    execution.plex_invite_and_share = lambda server, email, libraries_names, **kwargs: (
        plex_calls.append(kwargs)
        or {
            "state": "pending", "is_pending": True, "is_friend": False,
            "external_user_id": None, "username": None,
        }
    )
    plex_status = execution.process_migration_user(
        db,
        {"id": 21, "source_server_id": 1, "destination_server_id": 3, "destination_type": "plex"},
        dict(db.query_one("SELECT * FROM migration_users WHERE id=201")),
    )
    assert plex_status == "waiting_acceptance"
    assert plex_calls == [{"raise_on_update_error": True}]
    plex_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=201")["result_json"])
    assert plex_result["plex_invited_at"]
    assert plex_result["plex_last_checked_at"]
    assert db.query_one("SELECT COUNT(*) AS total FROM media_users WHERE server_id=3 AND vodum_user_id=10")["total"] == 1
    assert db.query_one("SELECT COUNT(*) AS total FROM media_user_libraries WHERE media_user_id=100")["total"] == 1

    execution.plex_invite_and_share = lambda server, email, libraries_names, **kwargs: {
        "state": "friend", "is_pending": False, "is_friend": True,
        "external_user_id": "plex-alice", "username": "alice",
    }
    accepted_status = execution.process_migration_user(
        db,
        {"id": 21, "source_server_id": 1, "destination_server_id": 3, "destination_type": "plex"},
        dict(db.query_one("SELECT * FROM migration_users WHERE id=201")),
    )
    assert accepted_status == "completed"
    assert db.query_one("SELECT accepted_at FROM media_users WHERE server_id=3 AND vodum_user_id=10")["accepted_at"]
    accepted_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=201")["result_json"])
    assert accepted_result["plex_accepted_at"]

    db.execute(
        "INSERT INTO migration_users(id,campaign_id,vodum_user_id,source_media_user_id,status,eligibility) VALUES(203,20,10,100,'processing','already_present')"
    )
    db.execute("UPDATE media_users SET details_json='{}' WHERE server_id=2 AND vodum_user_id=10")
    password_calls = []
    execution.jellyfin_set_password = lambda *args, **kwargs: password_calls.append((args, kwargs))
    preexisting_status = execution.process_migration_user(
        db,
        {"id": 20, "source_server_id": 1, "destination_server_id": 2, "destination_type": "jellyfin"},
        dict(db.query_one("SELECT * FROM migration_users WHERE id=203")),
    )
    assert preexisting_status == "completed"
    assert password_calls == []
    preexisting_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=203")["result_json"])
    assert preexisting_result["destination_validation_method"] == "existing_account"

    db.execute("UPDATE vodum_users SET username='',email='' WHERE id=11")
    db.execute("INSERT INTO migration_users(id,campaign_id,vodum_user_id,source_media_user_id,status,eligibility) VALUES(204,21,11,101,'processing','ready')")
    db.execute("INSERT INTO migration_library_mappings VALUES(4,21,2,5,'mapped')")
    execution.plex_invite_and_share = lambda server, email, libraries_names, **kwargs: {
        "state": "pending", "is_pending": True, "is_friend": False,
        "external_user_id": None, "username": None,
        "received_email": email,
    }
    assert execution.process_migration_user(
        db,
        {"id": 21, "source_server_id": 1, "destination_server_id": 3, "destination_type": "plex"},
        dict(db.query_one("SELECT * FROM migration_users WHERE id=204")),
    ) == "waiting_acceptance"
    assert db.query_one("SELECT email FROM media_users WHERE server_id=3 AND vodum_user_id=11")["email"] == "bob@example.com"

    reminders = []
    communications.select_comm_templates_for_user = lambda **kwargs: [{"id": 9}]
    communications.schedule_template_notification = lambda **kwargs: reminders.append(kwargs)
    db.execute(
        "UPDATE migration_users SET result_json=? WHERE id=201",
        (json.dumps({"plex_invited_at": "2020-01-01 00:00:00"}),),
    )
    execution.plex_invite_and_share = lambda server, email, libraries_names, **kwargs: {
        "state": "pending", "is_pending": True, "is_friend": False,
        "external_user_id": None, "username": None,
    }
    assert execution.process_migration_user(
        db,
        {"id": 21, "source_server_id": 1, "destination_server_id": 3, "destination_type": "plex"},
        dict(db.query_one("SELECT * FROM migration_users WHERE id=201")),
    ) == "waiting_acceptance"
    assert len(reminders) == 1
    reminded_result = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=201")["result_json"])
    assert reminded_result["plex_reminder_count"] == 1
    assert execution.process_migration_user(
        db,
        {"id": 21, "source_server_id": 1, "destination_server_id": 3, "destination_type": "plex"},
        dict(db.query_one("SELECT * FROM migration_users WHERE id=201")),
    ) == "waiting_acceptance"
    assert len(reminders) == 1

    print("OK - Phase 1 creates destination-only accounts and preserves per-user source access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
