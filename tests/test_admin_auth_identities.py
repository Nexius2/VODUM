import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.admin_auth_identities import (
    AdminIdentityConflict,
    get_admin_auth_discovery_token,
    link_admin_auth_identity,
    unlink_admin_auth_identity,
    sync_local_admin_identity,
    set_admin_auth_discovery_token,
)


class Db:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE admin_auth_identities(
              id INTEGER PRIMARY KEY, admin_account_id INTEGER, provider TEXT,
              provider_subject TEXT, display_name TEXT, display_email TEXT,
              discovery_token_enc TEXT,
              is_active INTEGER, linked_at TEXT DEFAULT CURRENT_TIMESTAMP,
              last_login_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()
    def execute(self, sql, params=()):
        result = self.conn.execute(sql, params)
        self.conn.commit()
        return result


class AdminAuthIdentityTests(unittest.TestCase):
    def test_link_is_idempotent_but_never_replaces_another_subject(self):
        db = Db()
        first = link_admin_auth_identity(
            db, provider="plex", subject="42", display_name="Owner"
        )
        second = link_admin_auth_identity(
            db, provider="plex", subject="42", display_name="New name"
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual("New name", second["display_name"])
        with self.assertRaises(AdminIdentityConflict):
            link_admin_auth_identity(db, provider="plex", subject="99")
        self.assertEqual(1, db.query_one("SELECT COUNT(*) AS n FROM admin_auth_identities")["n"])

        replaced = link_admin_auth_identity(
            db, provider="plex", subject="99", allow_replace=True
        )
        self.assertEqual(first["id"], replaced["id"])
        self.assertEqual("99", replaced["provider_subject"])
        self.assertTrue(unlink_admin_auth_identity(db, provider="plex"))
        self.assertFalse(unlink_admin_auth_identity(db, provider="plex"))
        with self.assertRaises(ValueError):
            unlink_admin_auth_identity(db, provider="local")

    def test_local_identity_is_created_and_tracks_email_changes(self):
        db = Db()
        created = sync_local_admin_identity(db, "Owner@Example.test")
        updated = sync_local_admin_identity(db, "new@example.test")
        self.assertEqual(created["id"], updated["id"])
        self.assertEqual("new@example.test", updated["provider_subject"])
        self.assertEqual("new@example.test", updated["display_email"])

    def test_discovery_token_is_encrypted_and_read_only_for_active_provider(self):
        db = Db()
        identity = link_admin_auth_identity(db, provider="plex", subject="42")
        with patch("core.admin_auth_identities.encrypt_secret", return_value="encrypted"), patch(
            "core.admin_auth_identities.decrypt_secret", return_value="plain-token"
        ):
            set_admin_auth_discovery_token(db, identity["id"], "plain-token")
            self.assertEqual("encrypted", db.query_one(
                "SELECT discovery_token_enc FROM admin_auth_identities WHERE id=?", (identity["id"],)
            )["discovery_token_enc"])
            self.assertEqual("plain-token", get_admin_auth_discovery_token(db, "plex"))


if __name__ == "__main__":
    unittest.main()
