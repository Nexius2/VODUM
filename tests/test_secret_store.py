from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.secret_store import (
    SECRET_PREFIX,
    SecretDecryptionError,
    decrypt_secret,
    decrypt_server_record,
    encryption_key_file_path,
    encrypt_communication_secrets,
    encrypt_server_secrets,
    encrypt_server_settings_json,
    encrypt_secret,
    find_plex_server_ids_by_token,
    install_encryption_key,
    keep_existing_secret,
)


class SecretStoreTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode("ascii")
        self.env = patch.dict(
            os.environ,
            {"VODUM_ENCRYPTION_KEY": self.key},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_round_trip_and_legacy_plaintext_compatibility(self):
        encrypted = encrypt_secret("very-secret")

        self.assertTrue(encrypted.startswith(SECRET_PREFIX))
        self.assertNotIn("very-secret", encrypted)
        self.assertEqual(decrypt_secret(encrypted), "very-secret")
        self.assertEqual(decrypt_secret("legacy-plaintext"), "legacy-plaintext")
        self.assertEqual(encrypt_secret(encrypted), encrypted)

    def test_wrong_key_fails_closed(self):
        encrypted = encrypt_secret("very-secret")

        with patch.dict(
            os.environ,
            {"VODUM_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii")},
            clear=False,
        ):
            with self.assertRaises(SecretDecryptionError):
                decrypt_secret(encrypted)

    def test_migrates_communication_secrets_idempotently(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY,
                    smtp_pass TEXT,
                    discord_bot_token TEXT
                );
                INSERT INTO settings(id, smtp_pass, discord_bot_token)
                VALUES (1, 'smtp-clear', 'legacy-discord-clear');

                CREATE TABLE discord_bots (
                    id INTEGER PRIMARY KEY,
                    token TEXT
                );
                INSERT INTO discord_bots(id, token) VALUES (1, 'bot-clear');
                """
            )

            self.assertEqual(encrypt_communication_secrets(conn), 2)
            first = conn.execute(
                "SELECT smtp_pass, discord_bot_token FROM settings WHERE id = 1"
            ).fetchone()
            bot = conn.execute("SELECT token FROM discord_bots WHERE id = 1").fetchone()

            self.assertEqual(decrypt_secret(first[0]), "smtp-clear")
            self.assertEqual(decrypt_secret(first[1]), "legacy-discord-clear")
            self.assertEqual(decrypt_secret(bot[0]), "bot-clear")
            self.assertEqual(encrypt_communication_secrets(conn), 0)
        finally:
            conn.close()

    def test_migrates_server_tokens_and_tautulli_keys_idempotently(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE servers (
                    id INTEGER PRIMARY KEY,
                    token TEXT,
                    settings_json TEXT
                );
                INSERT INTO servers(id, token, settings_json)
                VALUES (
                    1,
                    'plex-clear',
                    '{"tautulli":{"url":"http://tautulli","api_key":"tautulli-clear"}}'
                );
                """
            )

            self.assertEqual(encrypt_server_secrets(conn), 1)
            row = conn.execute(
                "SELECT id, token, settings_json FROM servers WHERE id = 1"
            ).fetchone()

            self.assertTrue(row[1].startswith(SECRET_PREFIX))
            self.assertNotIn("plex-clear", row[1])
            self.assertNotIn("tautulli-clear", row[2])

            server = decrypt_server_record(
                {"id": row[0], "token": row[1], "settings_json": row[2]}
            )
            settings = json.loads(server["settings_json"])
            self.assertEqual(server["token"], "plex-clear")
            self.assertEqual(settings["tautulli"]["api_key"], "tautulli-clear")
            self.assertEqual(encrypt_server_secrets(conn), 0)
        finally:
            conn.close()

    def test_server_settings_preserve_invalid_or_unrelated_json(self):
        self.assertEqual(encrypt_server_settings_json("invalid"), "invalid")
        self.assertEqual(
            encrypt_server_settings_json('{"feature":{"enabled":true}}'),
            '{"feature":{"enabled":true}}',
        )

    def test_finds_linked_plex_servers_using_decrypted_tokens(self):
        class FakeDb:
            def query(self, sql, params=()):
                return [
                    {"id": 1, "name": "A", "type": "plex", "token": encrypt_secret("shared")},
                    {"id": 2, "name": "B", "type": "plex", "token": encrypt_secret("other")},
                    {"id": 3, "name": "C", "type": "plex", "token": encrypt_secret("shared")},
                ]

        self.assertEqual(find_plex_server_ids_by_token(FakeDb(), "shared"), [1, 3])

    def test_blank_secret_submission_keeps_existing_value(self):
        self.assertEqual(keep_existing_secret("", "existing"), "existing")
        self.assertEqual(keep_existing_secret(None, "existing"), "existing")
        self.assertEqual(keep_existing_secret(" replacement ", "existing"), "replacement")

    def test_creates_persistent_key_file_when_env_key_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "vodum.encryption_key"
            with patch.dict(
                os.environ,
                {
                    "VODUM_ENCRYPTION_KEY": "",
                    "VODUM_ENCRYPTION_KEY_FILE": str(key_path),
                },
                clear=False,
            ):
                encrypted = encrypt_secret("persisted")
                self.assertTrue(key_path.is_file())
                self.assertEqual(decrypt_secret(encrypted), "persisted")

    def test_installs_restored_key_with_persistent_file(self):
        restored_key = Fernet.generate_key()
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "restored.key"
            with patch.dict(
                os.environ,
                {
                    "VODUM_ENCRYPTION_KEY": "",
                    "VODUM_ENCRYPTION_KEY_FILE": str(key_path),
                },
                clear=False,
            ):
                self.assertEqual(install_encryption_key(restored_key), key_path)
                self.assertEqual(encryption_key_file_path().read_bytes(), restored_key)

    def test_rejects_restore_key_conflicting_with_environment(self):
        with self.assertRaisesRegex(
            SecretDecryptionError,
            "different encryption key",
        ):
            install_encryption_key(Fernet.generate_key())


if __name__ == "__main__":
    unittest.main()
