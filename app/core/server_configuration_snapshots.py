"""Last configuration read from each server, kept in VODUM.

The Compliance pages work from these snapshots, so opening them never calls
every server at once: with 2 or 200 servers the page answers from the database,
and servers are read again one by one (refresh) when the admin asks for it or
when a snapshot is missing. Secrets are never stored.
"""

from __future__ import annotations

import json
import time

from core.server_configuration import ServerConfigurationError, load_media_server, read_loaded_server

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_snapshots (
 server_id INTEGER PRIMARY KEY,
 provider TEXT NOT NULL DEFAULT '',
 read_at TEXT,
 error TEXT,
 settings_json TEXT NOT NULL DEFAULT '[]'
);
"""

_KEPT = ("key", "compare_key", "label", "summary", "category", "library", "source", "value", "default", "type",
         "choices", "writable", "advanced", "modified")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _clean(settings) -> list[dict]:
    return [{key: item.get(key) for key in _KEPT} for item in settings or [] if not item.get("sensitive")]


def save_read(db, server_id, provider, result) -> None:
    """Store a full read of one server (replaces the previous snapshot)."""
    db.execute(
        """INSERT INTO config_snapshots(server_id, provider, read_at, error, settings_json) VALUES (?,?,?,?,?)
           ON CONFLICT(server_id) DO UPDATE SET provider=excluded.provider, read_at=excluded.read_at,
             error=excluded.error, settings_json=excluded.settings_json""",
        (int(server_id), provider or "", result.get("read_at") or _now(), None,
         json.dumps(_clean(result.get("settings")), ensure_ascii=False)),
    )


def save_error(db, server_id, provider, error) -> None:
    """Keep the last good settings, but say the server could not be read."""
    db.execute(
        """INSERT INTO config_snapshots(server_id, provider, read_at, error) VALUES (?,?,?,?)
           ON CONFLICT(server_id) DO UPDATE SET error=excluded.error""",
        (int(server_id), provider or "", None, str(error)),
    )


def merge_read(db, server_id, result) -> None:
    """A partial read (compliance check, verification after a change) refreshes the values it holds."""
    if not result or result.get("error"):
        return
    row = db.query_one("SELECT settings_json FROM config_snapshots WHERE server_id=?", (int(server_id),))
    if not row:
        return  # No full snapshot yet: the next refresh reads everything.
    settings = {item["compare_key"]: item for item in _json(row["settings_json"])}
    for item in _clean(result.get("settings")):
        settings[item["compare_key"]] = item
    db.execute("UPDATE config_snapshots SET settings_json=?, error=NULL WHERE server_id=?",
               (json.dumps(list(settings.values()), ensure_ascii=False), int(server_id)))


def _json(raw):
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def load(db, server_ids) -> dict:
    """{server_id: {"read_at", "error", "settings"}} for the servers that have a snapshot."""
    ids = [int(server_id) for server_id in server_ids]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = db.query(f"SELECT * FROM config_snapshots WHERE server_id IN ({marks})", tuple(ids)) or []
    return {int(row["server_id"]): {"read_at": row["read_at"], "error": row["error"],
                                    "settings": _json(row["settings_json"])} for row in rows}


def refresh(db, server_id) -> dict:
    """Read one server now and store it. Returns {"ok", "error", "read_at"}."""
    try:
        server, libraries = load_media_server(db, server_id)
    except ServerConfigurationError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = read_loaded_server(server, libraries)
    except ServerConfigurationError as exc:
        save_error(db, server_id, server["type"], str(exc))
        return {"ok": False, "error": str(exc)}
    save_read(db, server_id, server["type"], result)
    from core.server_configuration_compliance import record_read
    record_read(db, server_id, result)  # A full read also refreshes compliance.
    return {"ok": True, "error": None, "read_at": result.get("read_at")}
