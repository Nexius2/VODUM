#!/usr/bin/env python3
import os
import sqlite3
import sys
from pathlib import Path
from shutil import move

MIGRATION_VERSION = 3
MIGRATION_NAME = "20260330_migrate_v2_to_v3"

COPY_TABLES_IN_ORDER = [
    "settings",
    "auth_login_attempts",
    "vodum_users",
    "user_identities",
    "servers",
    "libraries",
    "media_users",
    "media_user_libraries",
    "subscription_gift_runs",
    "subscription_gift_run_users",
    "user_referral_settings",
    "user_referrals",
    "user_referral_events",
    "email_templates",
    "welcome_email_templates",
    "sent_emails",
    "mail_campaigns",
    "comm_templates",
    "comm_template_attachments",
    "comm_scheduled",
    "comm_campaigns",
    "comm_campaign_attachments",
    "comm_campaign_targets",
    "comm_history",
    "tasks",
    "media_jobs",
    "tautulli_import_jobs",
    "media_sessions",
    "media_events",
    "media_session_history",
    "monitoring_snapshots",
    "stream_policies",
    "stream_enforcement_state",
    "stream_enforcements",
    "discord_bots",
    "discord_templates",
    "sent_discord",
    "discord_campaigns",
]

def log(message: str) -> None:
    print(f"[MIGRATION_V2_TO_V3] {message}", flush=True)

def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def cleanup_sqlite_sidecars(db_path: str) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = f"{db_path}{suffix}"
        if os.path.exists(sidecar):
            os.remove(sidecar)

def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None

def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    return [row["name"] for row in rows]

def copy_common_columns(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    if not table_exists(src, table):
        log(f"Skip {table}: source table missing")
        return
    if not table_exists(dst, table):
        log(f"Skip {table}: destination table missing")
        return

    src_cols = get_columns(src, table)
    dst_cols = get_columns(dst, table)

    common_cols = [col for col in dst_cols if col in src_cols]

    if not common_cols:
        log(f"Skip {table}: no common columns")
        return

    select_cols = ", ".join(quote_ident(c) for c in common_cols)
    insert_cols = ", ".join(quote_ident(c) for c in common_cols)
    placeholders = ", ".join("?" for _ in common_cols)

    rows = src.execute(f"SELECT {select_cols} FROM {quote_ident(table)}").fetchall()
    if not rows:
        log(f"{table}: 0 row")
        return

    insert_verb = "INSERT"
    if table in ("settings", "user_referral_settings"):
        insert_verb = "INSERT OR REPLACE"

    dst.executemany(
        f"{insert_verb} INTO {quote_ident(table)} ({insert_cols}) VALUES ({placeholders})",
        [tuple(row[c] for c in common_cols) for row in rows],
    )
    log(f"{table}: {len(rows)} row(s) copied")

def migrate_subscription_templates(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    table = "subscription_templates"

    if not table_exists(src, table):
        log("Skip subscription_templates: source table missing")
        return

    rows = src.execute("SELECT * FROM subscription_templates").fetchall()
    if not rows:
        log("subscription_templates: 0 row")
        return

    src_cols = set(rows[0].keys())

    for row in rows:
        dst.execute(
            """
            INSERT INTO subscription_templates (
                id,
                name,
                notes,
                duration_days,
                subscription_value,
                policies_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["name"],
                row["notes"] if "notes" in src_cols else None,
                row["duration_days"] if "duration_days" in src_cols and row["duration_days"] is not None else 30,
                row["subscription_value"] if "subscription_value" in src_cols and row["subscription_value"] is not None else 0,
                row["policies_json"] if "policies_json" in src_cols and row["policies_json"] else "[]",
                row["created_at"] if "created_at" in src_cols else None,
                row["updated_at"] if "updated_at" in src_cols else None,
            ),
        )

    log(f"subscription_templates: {len(rows)} row(s) copied")

def migrate_schema_meta(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    if table_exists(src, "schema_migrations"):
        rows = src.execute(
            "SELECT version, name, applied_at FROM schema_migrations WHERE version < ? ORDER BY version",
            (MIGRATION_VERSION,),
        ).fetchall()
        for row in rows:
            dst.execute(
                """
                INSERT OR IGNORE INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (row["version"], row["name"], row["applied_at"]),
            )

    dst.execute("UPDATE schema_version SET version = ? WHERE id = 1", (MIGRATION_VERSION,))
    dst.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (version, name)
        VALUES (?, ?)
        """,
        (MIGRATION_VERSION, MIGRATION_NAME),
    )

def validate_counts(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    tables_to_check = COPY_TABLES_IN_ORDER + ["subscription_templates"]

    for table in tables_to_check:
        if not table_exists(src, table) or not table_exists(dst, table):
            continue

        src_count = src.execute(f"SELECT COUNT(*) AS c FROM {quote_ident(table)}").fetchone()["c"]
        dst_count = dst.execute(f"SELECT COUNT(*) AS c FROM {quote_ident(table)}").fetchone()["c"]

        if src_count != dst_count:
            raise RuntimeError(
                f"Count mismatch for table '{table}': source={src_count}, destination={dst_count}"
            )

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 /app/migrations/20260330_migrate_v2_to_v3.py /path/to/database.db")
        return 1

    old_db_path = os.path.abspath(sys.argv[1])
    root_dir = Path(__file__).resolve().parent.parent
    tables_v3_path = root_dir / "tables_v3.sql"

    if not os.path.isfile(old_db_path):
        raise FileNotFoundError(f"Source database not found: {old_db_path}")

    if not tables_v3_path.is_file():
        raise FileNotFoundError(f"tables_v3.sql not found: {tables_v3_path}")

    tmp_db_path = f"{old_db_path}.tmp_v3"

    if os.path.exists(tmp_db_path):
        os.remove(tmp_db_path)

    log(f"Create target V3 database from: {tables_v3_path}")

    dst = sqlite3.connect(tmp_db_path)
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys = OFF")

    with open(tables_v3_path, "r", encoding="utf-8") as f:
        dst.executescript(f.read())
    dst.commit()
    dst.close()

    src = connect(old_db_path)
    dst = connect(tmp_db_path)

    try:
        dst.execute("BEGIN")

        for table in COPY_TABLES_IN_ORDER:
            copy_common_columns(src, dst, table)

        migrate_subscription_templates(src, dst)
        migrate_schema_meta(src, dst)

        dst.commit()

        validate_counts(src, dst)

        fk_errors = dst.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"foreign_key_check failed: {len(fk_errors)} error(s)")

    except Exception:
        dst.rollback()
        dst.close()
        src.close()
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)
        raise

    dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    dst.close()
    src.close()

    cleanup_sqlite_sidecars(old_db_path)
    cleanup_sqlite_sidecars(tmp_db_path)

    move(tmp_db_path, old_db_path)
    log("Migration V2 -> V3 completed successfully")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())