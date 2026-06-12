"""Validate Jellyfin password changes through the credential service."""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

jellyfin_users = types.ModuleType("core.providers.jellyfin_users")
jellyfin_users.jellyfin_set_password = lambda *_args, **_kwargs: None
sys.modules["core.providers.jellyfin_users"] = jellyfin_users

from core import user_credentials  # noqa: E402


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()


def main() -> int:
    db = TestDB()
    db.conn.executescript(
        """
        CREATE TABLE servers(id INTEGER PRIMARY KEY,name TEXT,type TEXT,url TEXT,local_url TEXT,public_url TEXT,token TEXT);
        CREATE TABLE media_users(
          id INTEGER PRIMARY KEY,server_id INTEGER,vodum_user_id INTEGER,external_user_id TEXT,
          username TEXT,type TEXT,stored_password TEXT
        );
        INSERT INTO servers VALUES(1,'JF A','jellyfin','http://a',NULL,NULL,'a');
        INSERT INTO servers VALUES(2,'JF B','jellyfin','http://b',NULL,NULL,'b');
        INSERT INTO media_users VALUES(10,1,100,'jf-a','alice','jellyfin','legacy-a');
        INSERT INTO media_users VALUES(11,2,100,'jf-b','alice','jellyfin','legacy-b');
        """
    )
    calls = []
    user_credentials.jellyfin_set_password = lambda server, native_id, password: calls.append(
        (server["server_id"], native_id, password)
    )
    result = user_credentials.change_jellyfin_password(db, 100, "new-secret", {2})
    assert result == {"ok": True, "updated": 1, "errors": []}
    assert calls == [(2, "jf-b", "new-secret")]
    assert db.query("SELECT stored_password FROM media_users WHERE id=11")[0]["stored_password"] is None
    assert db.query("SELECT stored_password FROM media_users WHERE id=10")[0]["stored_password"] == "legacy-a"

    route_text = (ROOT / "app" / "routes" / "users_detail.py").read_text(encoding="utf-8")
    assert "jellyfin_set_password" not in route_text
    assert "change_jellyfin_password" in route_text
    print("OK - Jellyfin password changes are isolated in the credential service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
