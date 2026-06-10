from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_tables_sql_builds_a_valid_current_schema(self):
        schema_sql = (ROOT / "tables.sql").read_text(encoding="utf-8")
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(schema_sql)

            version = conn.execute(
                "SELECT version FROM schema_version WHERE id = 1"
            ).fetchone()
            self.assertEqual(version, (2,))

            migration = conn.execute(
                "SELECT name FROM schema_migrations WHERE version = 2"
            ).fetchone()
            self.assertEqual(migration, ("init_v2",))

            required_tables = {
                "settings",
                "tasks",
                "vodum_users",
                "media_users",
                "servers",
                "libraries",
                "media_jobs",
                "stream_policies",
            }
            actual_tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(required_tables.issubset(actual_tables))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_entrypoint_uses_a_non_conflicting_v1_import_marker(self):
        entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn(
            "VALUES (20251213, '20251213_import_v1_into_v2');",
            entrypoint,
        )
        self.assertNotIn("VALUES (3, '20250402_rebuild_from_v1');", entrypoint)

    def test_obsolete_v3_rebuild_is_not_shipped(self):
        self.assertFalse(
            (ROOT / "migrations" / "20260330_migrate_v2_to_v3.py").exists()
        )
        self.assertFalse((ROOT / "tables_v3.sql").exists())

    def test_obsolete_users_table_migration_is_not_shipped(self):
        self.assertFalse(
            (
                ROOT
                / "migrations"
                / "20251215_add_jellyfin_id_and_nullable_plex_id.py"
            ).exists()
        )
        entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertNotIn("20251215_add_jellyfin_id_and_nullable_plex_id", entrypoint)

    def test_entrypoint_uses_waitress_production_server(self):
        entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("exec waitress-serve", entrypoint)
        self.assertIn("run:app", entrypoint)
        self.assertIn("--max-request-body-size=", entrypoint)
        self.assertIn("VODUM_MAX_UPLOAD_MB", entrypoint)
        self.assertNotIn("exec python3 run.py", entrypoint)


if __name__ == "__main__":
    unittest.main()
