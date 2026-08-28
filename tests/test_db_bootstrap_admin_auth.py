import contextlib
import io
import sqlite3
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.db_bootstrap_admin_auth import ensure_admin_auth_schema


def table_exists(cursor, table):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


class AdminAuthBootstrapTests(unittest.TestCase):
    def run_schema(self, connection):
        with contextlib.redirect_stdout(io.StringIO()):
            ensure_admin_auth_schema(
                connection,
                connection.cursor(),
                table_exists=table_exists,
            )

    def test_fresh_schema_is_idempotent_and_provider_neutral(self):
        connection = sqlite3.connect(":memory:")
        self.run_schema(connection)
        self.run_schema(connection)

        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM admin_accounts")
        self.assertEqual(1, cursor.fetchone()[0])
        account = cursor.execute(
            "SELECT plex_client_identifier, plex_require_vodum_totp FROM admin_accounts"
        ).fetchone()
        self.assertTrue(account[0])
        self.assertEqual(0, account[1])
        cursor.execute("PRAGMA table_info(admin_auth_identities)")
        columns = {row[1] for row in cursor.fetchall()}
        self.assertTrue(
            {"provider", "provider_subject", "display_name", "display_email",
             "linked_at", "last_login_at", "is_active", "discovery_token_enc"}.issubset(columns)
        )
        self.assertNotIn("server_id", columns)
        cursor.execute("SELECT COUNT(*) FROM admin_auth_identities")
        self.assertEqual(0, cursor.fetchone()[0])
        cursor.execute("PRAGMA table_info(plex_discovery_candidates)")
        discovery_columns = {row[1] for row in cursor.fetchall()}
        self.assertTrue(
            {"discovery_id", "session_fingerprint", "provider_subject",
             "machine_identifier", "connections_json", "access_token_enc",
             "expires_at"}.issubset(discovery_columns)
        )

    def test_existing_local_admin_gets_one_metadata_identity(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE settings(
                id INTEGER PRIMARY KEY,
                admin_email TEXT,
                admin_password_hash TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO settings(id, admin_email, admin_password_hash)
            VALUES (1, ?, 'configured-hash')
            """,
            ("Owner@Example.test",),
        )

        self.run_schema(connection)
        self.run_schema(connection)

        rows = connection.execute(
            """
            SELECT provider, provider_subject, display_email, is_active
            FROM admin_auth_identities
            """
        ).fetchall()
        self.assertEqual(
            [("local", "owner@example.test", "Owner@Example.test", 1)],
            rows,
        )

    def test_email_without_local_password_does_not_create_active_identity(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE settings(
                id INTEGER PRIMARY KEY,
                admin_email TEXT,
                admin_password_hash TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO settings(id, admin_email) VALUES (1, 'pending@example.test')"
        )
        self.run_schema(connection)
        count = connection.execute(
            "SELECT COUNT(*) FROM admin_auth_identities"
        ).fetchone()[0]
        self.assertEqual(0, count)

    def test_schema_does_not_require_media_tables(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        self.run_schema(connection)
        connection.execute(
            """
            INSERT INTO admin_auth_identities(
                provider, provider_subject, display_name
            ) VALUES ('plex', 'plex-user-42', 'Owner')
            """
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
