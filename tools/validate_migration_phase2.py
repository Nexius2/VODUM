"""Validate Plex invitation reconciliation and automatic retry behavior."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

logging_utils = types.ModuleType("logging_utils")
logging_utils.get_logger = lambda *_args, **_kwargs: types.SimpleNamespace(
    error=lambda *_args, **_kwargs: None
)
sys.modules["logging_utils"] = logging_utils

tasks_engine = types.ModuleType("tasks_engine")
tasks_engine.task_logs = lambda *_args, **_kwargs: None
sys.modules["tasks_engine"] = tasks_engine

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

from tasks import migration_worker  # noqa: E402


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
        CREATE TABLE servers(id INTEGER PRIMARY KEY, type TEXT);
        CREATE TABLE tasks(name TEXT PRIMARY KEY, enabled INTEGER);
        CREATE TABLE migration_campaigns(
          id INTEGER PRIMARY KEY, source_server_id INTEGER, destination_server_id INTEGER,
          migration_type TEXT, migration_mode TEXT, status TEXT, updated_at TEXT,
          completed_at TEXT, started_at TEXT, scheduled_at TEXT, batch_size INTEGER
        );
        CREATE TABLE migration_users(
          id INTEGER PRIMARY KEY, campaign_id INTEGER, vodum_user_id INTEGER,
          status TEXT, eligibility TEXT, attempts INTEGER DEFAULT 0, last_error TEXT,
          started_at TEXT, updated_at TEXT, completed_at TEXT, result_json TEXT
        );
        INSERT INTO servers VALUES(2, 'plex');
        INSERT INTO tasks VALUES('migration_worker', 1);
        INSERT INTO migration_campaigns VALUES(10,1,2,'plex_to_plex','invite','waiting_users',CURRENT_TIMESTAMP,NULL,NULL,NULL,10);
        INSERT INTO migration_users VALUES(20,10,100,'waiting_acceptance','ready',0,NULL,NULL,datetime('now','-11 minutes'),NULL,NULL);
        """
    )

    migration_worker.process_migration_user = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("temporary Plex outage")
    )
    migration_worker.run(1, db)
    waiting = db.query_one("SELECT status, last_error FROM migration_users WHERE id=20")
    assert waiting["status"] == "waiting_acceptance"
    assert "temporary Plex outage" in waiting["last_error"]
    assert db.query_one("SELECT enabled FROM tasks WHERE name='migration_worker'")["enabled"] == 1

    db.execute("UPDATE migration_users SET updated_at=datetime('now','-11 minutes') WHERE id=20")
    migration_worker.process_migration_user = lambda *_args, **_kwargs: "completed"
    migration_worker.run(1, db)
    assert db.query_one("SELECT status FROM migration_users WHERE id=20")["status"] == "completed"
    assert db.query_one("SELECT status FROM migration_campaigns WHERE id=10")["status"] == "completed"
    assert db.query_one("SELECT enabled FROM tasks WHERE name='migration_worker'")["enabled"] == 0

    db.execute("UPDATE tasks SET enabled=1 WHERE name='migration_worker'")
    db.execute(
        "INSERT INTO migration_campaigns VALUES(11,1,2,'plex_to_plex','invite','running',CURRENT_TIMESTAMP,NULL,NULL,NULL,2)"
    )
    for user_id in (21, 22, 23):
        db.execute(
            "INSERT INTO migration_users VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, 11, user_id, "pending", "ready", 0, None, None, None, None, None),
        )
    migration_worker.process_migration_user = lambda *_args, **_kwargs: "completed"
    migration_worker.run(1, db)
    assert db.query_one("SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id=11 AND status='completed'")["total"] == 2
    assert db.query_one("SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id=11 AND status='pending'")["total"] == 1

    db.execute(
        "INSERT INTO migration_campaigns VALUES(13,1,2,'jellyfin_to_plex','invite','running',CURRENT_TIMESTAMP,NULL,NULL,NULL,10)"
    )
    db.execute(
        "INSERT INTO migration_users VALUES(31,13,301,'pending','already_present',0,NULL,NULL,NULL,NULL,NULL)"
    )
    migration_worker.run(1, db)
    assert db.query_one("SELECT status FROM migration_users WHERE id=31")["status"] == "completed"

    db.execute(
        "INSERT INTO migration_campaigns VALUES(12,1,2,'plex_to_plex','invite','scheduled',CURRENT_TIMESTAMP,NULL,NULL,'2999-01-01 00:00:00',10)"
    )
    migration_worker.run(1, db)
    assert db.query_one("SELECT status FROM migration_campaigns WHERE id=12")["status"] == "scheduled"

    db.execute(
        "INSERT INTO migration_users VALUES(30,12,300,'completed','ready',0,NULL,NULL,NULL,NULL,?)",
        (json.dumps({
            "encrypted_generated_password": "encrypted:expired",
            "credentials_expires_at": "2000-01-01 00:00:00",
            "credentials_pending_delivery": True,
        }),),
    )
    migration_worker.run(1, db)
    expired = json.loads(db.query_one("SELECT result_json FROM migration_users WHERE id=30")["result_json"])
    assert "encrypted_generated_password" not in expired
    assert expired["credentials_expired_at"]

    print("OK - Phase 2 retries Plex checks; scheduled and batched campaigns remain controlled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
