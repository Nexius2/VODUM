#!/usr/bin/env python3
"""
Smoke test VODUM - cycle warn_only / expired_subscription.

À placer dans: tools/smoke_expired_subscription_cycle.py
À lancer depuis la racine du projet:
    python tools/smoke_expired_subscription_cycle.py

Ce test utilise une DB SQLite temporaire en mémoire.
Il ne touche pas à /appdata/database.db.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

import types

# Stubs légers pour permettre le smoke test sans dépendances Flask/Cron dans un environnement minimal.
if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    class _Blueprint:
        def __init__(self, *args, **kwargs):
            pass
        def route(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    flask_stub.Blueprint = _Blueprint
    flask_stub.request = types.SimpleNamespace(get_json=lambda *a, **k: {}, form={})
    flask_stub.jsonify = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    sys.modules["flask"] = flask_stub

if "tasks_engine" not in sys.modules:
    tasks_engine_stub = types.ModuleType("tasks_engine")
    tasks_engine_stub.task_logs = lambda *args, **kwargs: None
    tasks_engine_stub.enable_and_run_task_by_name = lambda *args, **kwargs: True
    sys.modules["tasks_engine"] = tasks_engine_stub

if "communications_engine" not in sys.modules:
    communications_stub = types.ModuleType("communications_engine")
    communications_stub.select_comm_template_for_user = lambda *args, **kwargs: None
    communications_stub.schedule_template_notification = lambda *args, **kwargs: None
    sys.modules["communications_engine"] = communications_stub

if "logging_utils" not in sys.modules:
    logging_stub = types.ModuleType("logging_utils")
    class _Logger:
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
    logging_stub.get_logger = lambda *args, **kwargs: _Logger()
    logging_stub.is_debug_mode_enabled = lambda *args, **kwargs: False
    sys.modules["logging_utils"] = logging_stub

from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
sys.path.insert(0, str(APP_DIR))

# Évite que les helpers de log cherchent une DB réelle pendant ce smoke test.
os.environ.setdefault("DATABASE_PATH", ":memory:")

from tasks import expired_subscription_manager  # noqa: E402
from api import subscriptions as subscriptions_api  # noqa: E402


class TestDB:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchone()


def create_schema(db: TestDB) -> None:
    db.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            expiry_mode TEXT,
            warn_then_disable_days INTEGER,
            preavis_days INTEGER,
            reminder_days INTEGER
        )
    """)
    db.execute("""
        INSERT INTO settings(id, expiry_mode, warn_then_disable_days, preavis_days, reminder_days)
        VALUES (1, 'warn_only', 7, 30, 7)
    """)

    db.execute("""
        CREATE TABLE vodum_users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            expiration_date TEXT,
            status TEXT,
            last_status TEXT,
            status_changed_at TEXT
        )
    """)

    db.execute("""
        CREATE TABLE stream_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_type TEXT,
            scope_id INTEGER,
            provider TEXT,
            server_id INTEGER,
            is_enabled INTEGER,
            priority INTEGER,
            rule_type TEXT,
            rule_value_json TEXT
        )
    """)

    db.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            enabled INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle',
            updated_at TEXT,
            enabled_prev INTEGER
        )
    """)
    for name in ("stream_enforcer", "apply_plex_access_updates", "send_expiration_emails"):
        db.execute("INSERT INTO tasks(name, enabled, status) VALUES (?, 0, 'idle')", (name,))

    db.execute("""
        CREATE TABLE servers (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT
        )
    """)

    db.execute("""
        CREATE TABLE libraries (
            id INTEGER PRIMARY KEY,
            server_id INTEGER,
            name TEXT
        )
    """)

    db.execute("""
        CREATE TABLE media_users (
            id INTEGER PRIMARY KEY,
            vodum_user_id INTEGER,
            server_id INTEGER,
            type TEXT,
            role TEXT,
            accepted_at TEXT,
            external_user_id TEXT
        )
    """)

    db.execute("""
        CREATE TABLE media_user_libraries (
            media_user_id INTEGER,
            library_id INTEGER
        )
    """)

    db.execute("""
        CREATE TABLE media_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            action TEXT,
            vodum_user_id INTEGER,
            server_id INTEGER,
            library_id INTEGER,
            payload_json TEXT,
            status TEXT,
            processed INTEGER,
            success INTEGER,
            attempts INTEGER,
            dedupe_key TEXT UNIQUE,
            run_after TEXT,
            processed_at TEXT,
            locked_by TEXT,
            locked_until TEXT,
            last_error TEXT
        )
    """)


def seed_user_with_plex_access(db: TestDB) -> tuple[int, int]:
    user_id = 1
    media_user_id = 10
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    db.execute(
        "INSERT INTO vodum_users(id, username, expiration_date, status) VALUES (?, ?, ?, ?)",
        (user_id, "smoke-user", yesterday, "expired"),
    )
    db.execute("INSERT INTO servers(id, name, type) VALUES (1, 'Plex Test', 'plex')")
    db.execute("INSERT INTO libraries(id, server_id, name) VALUES (100, 1, 'Films')")
    db.execute(
        """
        INSERT INTO media_users(id, vodum_user_id, server_id, type, role, accepted_at, external_user_id)
        VALUES (?, ?, 1, 'plex', 'friend', '2026-01-01', 'plex-user-1')
        """,
        (media_user_id, user_id),
    )
    db.execute(
        "INSERT INTO media_user_libraries(media_user_id, library_id) VALUES (?, 100)",
        (media_user_id,),
    )
    return user_id, media_user_id


def count_expired_policy(db: TestDB, user_id: int) -> int:
    rows = db.query(
        "SELECT rule_value_json FROM stream_policies WHERE scope_type='user' AND scope_id=?",
        (user_id,),
    )
    total = 0
    for row in rows:
        rule = json.loads(row["rule_value_json"] or "{}")
        if rule.get("system_tag") == "expired_subscription":
            total += 1
    return total


def count_libraries(db: TestDB, media_user_id: int) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM media_user_libraries WHERE media_user_id=?",
        (media_user_id,),
    )
    return int(row["c"] or 0)


def count_jobs(db: TestDB, provider: str, action: str, user_id: int) -> int:
    row = db.query_one(
        """
        SELECT COUNT(*) AS c
        FROM media_jobs
        WHERE provider=? AND action=? AND vodum_user_id=? AND status='queued'
        """,
        (provider, action, user_id),
    )
    return int(row["c"] or 0)


def main() -> None:
    db = TestDB()
    create_schema(db)
    user_id, media_user_id = seed_user_with_plex_access(db)

    # Neutralise les effets externes pendant le test.
    expired_subscription_manager.task_logs = lambda *args, **kwargs: None
    subscriptions_api.enable_and_run_task_by_name = lambda *args, **kwargs: True
    subscriptions_api.select_comm_template_for_user = lambda *args, **kwargs: None
    subscriptions_api.schedule_template_notification = lambda *args, **kwargs: None

    expired_subscription_manager.run(task_id=1, db=db)

    assert count_expired_policy(db, user_id) == 1, "Policy expired_subscription non créée"
    assert count_libraries(db, media_user_id) == 1, "warn_only ne doit pas retirer les bibliothèques"
    assert count_jobs(db, "plex", "revoke", user_id) == 0, "warn_only ne doit pas créer de revoke Plex"

    renewed_date = (date.today() + timedelta(days=30)).isoformat()
    ok, msg = subscriptions_api.update_user_expiration(
        user_id,
        renewed_date,
        reason="smoke_test",
        db=db,
    )

    assert ok is True, msg
    assert count_expired_policy(db, user_id) == 0, "Policy expired_subscription non supprimée après renouvellement"
    assert count_jobs(db, "plex", "sync", user_id) == 1, "Sync Plex non créé après réactivation"

    print("OK - cycle warn_only validé : policy créée, accès conservés, policy supprimée au renouvellement, sync Plex créé.")


if __name__ == "__main__":
    main()
