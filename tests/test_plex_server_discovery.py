import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.plex_server_discovery import (
    PlexDiscoveryError,
    automatic_plex_suggestions,
    load_discovery,
    parse_plex_resources,
    store_discovery,
)


class SqliteDb:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE plex_discovery_candidates (
              id TEXT PRIMARY KEY, discovery_id TEXT NOT NULL,
              session_fingerprint TEXT NOT NULL, provider_subject TEXT NOT NULL,
              machine_identifier TEXT NOT NULL, name TEXT NOT NULL,
              is_owned INTEGER NOT NULL, presence INTEGER NOT NULL,
              connections_json TEXT NOT NULL, access_token_enc TEXT,
              expires_at INTEGER NOT NULL
            )
            """
        )
        self.connection.execute(
            "CREATE TABLE servers(id INTEGER PRIMARY KEY, type TEXT, server_identifier TEXT)"
        )

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)

    def query(self, sql, params=()):
        return self.connection.execute(sql, params).fetchall()


class PlexServerDiscoveryTests(unittest.TestCase):
    def test_resources_are_filtered_deduplicated_and_ranked(self):
        payload = b"""<MediaContainer>
          <Device name="Shared copy" provides="server" clientIdentifier="same" owned="0" presence="0" accessToken="old">
            <Connection uri="https://relay.example.test:443" local="0" relay="1" />
          </Device>
          <Device name="Owned" provides="server,player" clientIdentifier="same" owned="1" presence="1" accessToken="resource-secret">
            <Connection uri="http://192.168.1.20:32400/" local="1" relay="0" />
            <Connection uri="https://public.example.test:32400" local="0" relay="0" />
            <Connection uri="https://relay.example.test:443" local="0" relay="1" />
            <Connection uri="file:///etc/passwd" local="1" relay="0" />
            <Connection uri="https://user:password@example.test" local="0" relay="0" />
          </Device>
          <Device name="Player" provides="player" clientIdentifier="ignored" />
        </MediaContainer>"""
        resources = parse_plex_resources(payload, existing_identifiers={"same"})
        self.assertEqual(1, len(resources))
        server = resources[0]
        self.assertEqual("Owned", server["name"])
        self.assertTrue(server["owned"])
        self.assertTrue(server["already_added"])
        self.assertEqual(
            ["http://192.168.1.20:32400", "https://public.example.test:32400", "https://relay.example.test:443"],
            [item["uri"] for item in server["connections"]],
        )

    def test_invalid_xml_is_reported_as_safe_discovery_error(self):
        with self.assertRaises(PlexDiscoveryError):
            parse_plex_resources(b"not xml")

    def test_query_paths_and_credentials_are_not_accepted_as_server_bases(self):
        payload = b"""<MediaContainer><Device provides="server" clientIdentifier="m1" accessToken="t">
          <Connection uri="https://safe.test:32400/" />
          <Connection uri="https://safe.test:32400/web" />
          <Connection uri="https://safe.test:32400/?token=leak" />
          <Connection uri="https://user:pass@safe.test:32400" />
        </Device></MediaContainer>"""
        resources = parse_plex_resources(payload)
        self.assertEqual(["https://safe.test:32400"], [c["uri"] for c in resources[0]["connections"]])

    def test_ephemeral_store_encrypts_token_and_is_bound_to_session(self):
        db = SqliteDb()
        candidates = [{
            "machine_identifier": "machine-1", "name": "Living room",
            "owned": True, "presence": True, "access_token": "plain-secret",
            "connections": [{"uri": "https://plex.test", "local": False,
                             "relay": False, "protocol": "https"}],
        }]
        with patch("core.plex_server_discovery.encrypt_secret", side_effect=lambda value: f"enc:{value}"), patch(
            "core.plex_server_discovery.decrypt_secret", side_effect=lambda value: value.removeprefix("enc:")
        ):
            discovery_id = store_discovery(
                db, session_secret="browser-nonce", provider_subject="plex-user", candidates=candidates
            )
            stored = db.connection.execute(
                "SELECT session_fingerprint,access_token_enc FROM plex_discovery_candidates"
            ).fetchone()
            self.assertNotEqual("browser-nonce", stored["session_fingerprint"])
            self.assertEqual("enc:plain-secret", stored["access_token_enc"])
            self.assertEqual([], load_discovery(db, discovery_id=discovery_id, session_secret="other-browser"))
            loaded = load_discovery(db, discovery_id=discovery_id, session_secret="browser-nonce")
            self.assertEqual("plain-secret", loaded[0]["access_token"])
            self.assertEqual("plex-user", loaded[0]["provider_subject"])

    def test_preview_template_never_references_access_token(self):
        template = (APP_DIR.parent / "templates" / "servers" / "plex_discovery.html").read_text(encoding="utf-8")
        self.assertNotIn("access_token", template)
        self.assertNotIn("checked", template)
        self.assertIn("preferred_url_", template)

    def test_automatic_suggestions_hide_already_configured_servers(self):
        db = SqliteDb()
        db.execute("INSERT INTO servers(type,server_identifier) VALUES('plex','existing')")
        candidates = [
            {"machine_identifier": "existing", "name": "Old", "owned": True,
             "presence": True, "access_token": "old-token", "connections": []},
            {"machine_identifier": "new", "name": "New", "owned": True,
             "presence": True, "access_token": "new-token",
             "connections": [{"uri": "https://new.test", "local": False,
                              "relay": False, "protocol": "https"}]},
        ]
        with patch("core.plex_server_discovery.discover_plex_resources", return_value=candidates), patch(
            "core.plex_server_discovery.store_discovery", return_value="discovery-1"
        ):
            suggestions, context = automatic_plex_suggestions(
                db, provider_subject="plex-user", account_token="account-token",
                context=None, return_to="servers",
            )
        self.assertEqual(["new"], [item["machine_identifier"] for item in suggestions])
        self.assertNotIn("access_token", suggestions[0])
        self.assertEqual("discovery-1", context["id"])


if __name__ == "__main__":
    unittest.main()
