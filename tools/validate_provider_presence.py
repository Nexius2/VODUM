"""Validate provider-presence checks and route/service separation."""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

http_security = types.ModuleType("core.http_security")
http_security.plex_server_http_session = lambda _server: None
sys.modules["core.http_security"] = http_security

plex_connection = types.ModuleType("core.plex_connection")
plex_connection.find_working_plex_base_url = lambda server, **_kwargs: str(server.get("url") or "")
sys.modules["core.plex_connection"] = plex_connection

plex_rate_limit = types.ModuleType("core.plex_rate_limit")
plex_rate_limit.install_plex_rate_limit = lambda *_args, **_kwargs: None
sys.modules["core.plex_rate_limit"] = plex_rate_limit

jellyfin_users = types.ModuleType("core.providers.jellyfin_users")
jellyfin_users.jellyfin_list_users = lambda _server: []
sys.modules["core.providers.jellyfin_users"] = jellyfin_users

from core import provider_presence  # noqa: E402


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


def main() -> int:
    db = TestDB()
    db.conn.executescript(
        """
        CREATE TABLE vodum_users(id INTEGER PRIMARY KEY, username TEXT, email TEXT);
        CREATE TABLE servers(
          id INTEGER PRIMARY KEY, name TEXT, type TEXT, url TEXT,
          local_url TEXT, public_url TEXT, token TEXT
        );
        CREATE TABLE media_users(
          id INTEGER PRIMARY KEY, server_id INTEGER, vodum_user_id INTEGER,
          external_user_id TEXT, username TEXT, email TEXT, type TEXT, role TEXT,
          joined_at TEXT, accepted_at TEXT, details_json TEXT
        );
        INSERT INTO vodum_users VALUES(1,'alice','alice@example.com');
        INSERT INTO servers VALUES(10,'Jellyfin','jellyfin','http://jf',NULL,NULL,'token');
        INSERT INTO media_users VALUES(20,10,1,'jf-alice','alice','alice@example.com','jellyfin','user',NULL,NULL,'{}');
        """
    )

    provider_presence.jellyfin_list_users = lambda _server: [{"Id": "jf-alice", "Name": "alice"}]
    present = provider_presence.check_jellyfin_account_presence(
        {"type": "jellyfin", "url": "http://jf", "token": "token"},
        {"external_user_id": "jf-alice", "username": "alice"},
    )
    assert present["state"] == "present"
    assert present["can_return_on_sync"] is True

    incomplete = provider_presence.check_plex_account_presence(
        {"type": "plex", "url": "", "token": ""},
        {"username": "alice"},
    )
    assert incomplete["state"] == "unknown"
    assert incomplete["can_return_on_sync"] is True

    summary = provider_presence.build_user_delete_check(db, 1)
    assert summary["linked_accounts_total"] == 1
    assert summary["still_exists_total"] == 1
    assert summary["will_return_on_sync"] is True

    route_text = (ROOT / "app" / "routes" / "users_actions.py").read_text(encoding="utf-8")
    forbidden = (
        "plexapi.server",
        "jellyfin_list_users",
        "plex_server_http_session",
        "matches_plex_identity",
    )
    assert not any(name in route_text for name in forbidden)
    assert "build_user_delete_check" in route_text

    print("OK - provider presence checks are centralized outside the user-action routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
