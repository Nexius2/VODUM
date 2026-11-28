"""Configuration Manager step 2: profiles, server groups and the comparison matrix.

Profiles and groups are stored in VODUM only. Nothing here writes to Plex or
Jellyfin: reading uses core.server_configuration, which is read-only.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from core.server_configuration import (
    CATEGORIES, ServerConfigurationError, load_media_server, read_loaded_server,
)
from core import server_configuration_recommendations as recommendations

PROVIDERS = ("plex", "jellyfin")
NAME_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 300
VALUE_MAX_LENGTH = 1000
MAX_COMPARED_SERVERS = 12
READ_WORKERS = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_profiles (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 settings_json TEXT NOT NULL DEFAULT '{}',
 source_server_id INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(provider, name)
);
CREATE TABLE IF NOT EXISTS config_groups (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE,
 description TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS config_group_servers (
 group_id INTEGER NOT NULL REFERENCES config_groups(id) ON DELETE CASCADE,
 server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
 PRIMARY KEY (group_id, server_id)
);
CREATE TABLE IF NOT EXISTS config_profile_targets (
 profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE,
 target_type TEXT NOT NULL CHECK (target_type IN ('server','group')),
 target_id INTEGER NOT NULL,
 PRIMARY KEY (profile_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS config_server_profile_choice (
 server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
 profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE
);
"""

# Never copied into a profile by default: values that belong to one machine.
_MACHINE_SPECIFIC = re.compile(
    r"(path|port|url|uri|address|interface|device|certificate|friendlyname|servername|"
    r"bindto|lannetwork|localnetwork|publishedserver|knownproxies|directory|folder|"
    r"vaapi|qsv|nvenc|hardwaredevice|machine|identifier|uuid|token|password|apikey|mail)",
    re.IGNORECASE,
)


class ProfileError(ValueError):
    """A request the admin must correct; the message is a translation key."""


def normalize_value(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    text = str(value).strip()
    return {"True": "true", "False": "false"}.get(text, text)


def is_machine_specific(key) -> bool:
    """Settings expected to differ between servers (name, port, paths...)."""
    return bool(_MACHINE_SPECIFIC.search(str(key or "").rsplit(".", 1)[-1]))


def is_profile_eligible(item: dict) -> bool:
    """Settings a profile may hold: writable, not secret, not machine specific."""
    if item.get("sensitive") or not item.get("writable"):
        return False
    if item.get("source") == "scheduled_task":
        return False
    return not is_machine_specific(item.get("compare_key") or item.get("key"))


def _clean_name(value, limit=NAME_MAX_LENGTH):
    return " ".join(str(value or "").split())[:limit]


def _load_settings(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _profile_row(row) -> dict:
    profile = dict(row)
    profile["settings"] = _load_settings(profile.pop("settings_json", "{}"))
    return profile


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def list_profiles(db, provider=None) -> list[dict]:
    sql = "SELECT * FROM config_profiles"
    params = ()
    if provider:
        sql += " WHERE provider=?"
        params = (provider,)
    return [_profile_row(row) for row in db.query(sql + " ORDER BY provider, name COLLATE NOCASE", params) or []]


def get_profile(db, profile_id) -> dict | None:
    row = db.query_one("SELECT * FROM config_profiles WHERE id=?", (int(profile_id),))
    return _profile_row(row) if row else None


def _check_name(db, provider, name, exclude_id=None):
    if not name:
        raise ProfileError("config_profile_name_required")
    row = db.query_one("SELECT id FROM config_profiles WHERE provider=? AND name=? COLLATE NOCASE AND id!=?",
                       (provider, name, int(exclude_id or 0)))
    if row:
        raise ProfileError("config_profile_name_taken")


def settings_from_read(result) -> tuple[dict, int]:
    """Profile entries from a server read, and the number of settings left out."""
    settings, excluded = {}, 0
    for item in result.get("settings") or []:
        if not is_profile_eligible(item):
            excluded += 1
            continue
        settings[item["compare_key"]] = {
            "value": normalize_value(item.get("value")),
            "label": item.get("label") or item["compare_key"],
            "category": item.get("category") if item.get("category") in CATEGORIES else "advanced",
            "type": item.get("type") or "text",
            "choices": item.get("choices") or [],
            "library": item.get("library") or None,
        }
    return settings, excluded


def create_profile(db, provider, name, description="", settings=None, source_server_id=None) -> int:
    if provider not in PROVIDERS:
        raise ProfileError("config_profile_provider_required")
    name = _clean_name(name)
    _check_name(db, provider, name)
    cursor = db.execute(
        """INSERT INTO config_profiles(provider,name,description,settings_json,source_server_id)
           VALUES (?,?,?,?,?)""",
        (provider, name, _clean_name(description, DESCRIPTION_MAX_LENGTH),
         json.dumps(settings or {}, ensure_ascii=False, sort_keys=True), source_server_id),
    )
    return int(cursor.lastrowid)


def update_profile(db, profile_id, *, name, description, values, removed=()):
    profile = get_profile(db, profile_id)
    if not profile:
        raise ProfileError("config_profile_not_found")
    name = _clean_name(name)
    _check_name(db, profile["provider"], name, exclude_id=profile["id"])
    settings = profile["settings"]
    for key in removed or ():
        settings.pop(key, None)
    for key, value in (values or {}).items():
        if key in settings:
            settings[key]["value"] = normalize_value(value)[:VALUE_MAX_LENGTH]
    db.execute("""UPDATE config_profiles SET name=?,description=?,settings_json=?,updated_at=CURRENT_TIMESTAMP
                  WHERE id=?""",
               (name, _clean_name(description, DESCRIPTION_MAX_LENGTH),
                json.dumps(settings, ensure_ascii=False, sort_keys=True), profile["id"]))


def merge_profile_settings(db, profile_id, new_settings, *, replace_values=False) -> int:
    """Add settings read from a server; existing expected values are kept unless asked."""
    profile = get_profile(db, profile_id)
    if not profile:
        raise ProfileError("config_profile_not_found")
    settings = profile["settings"]
    added = 0
    for key, entry in new_settings.items():
        if key not in settings:
            added += 1
            settings[key] = entry
        elif replace_values:
            settings[key]["value"] = entry["value"]
    db.execute("UPDATE config_profiles SET settings_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (json.dumps(settings, ensure_ascii=False, sort_keys=True), profile["id"]))
    return added


def duplicate_profile(db, profile_id) -> int:
    profile = get_profile(db, profile_id)
    if not profile:
        raise ProfileError("config_profile_not_found")
    base = _clean_name(profile["name"] + " (copy)")
    name, number = base, 2
    while db.query_one("SELECT 1 FROM config_profiles WHERE provider=? AND name=? COLLATE NOCASE",
                       (profile["provider"], name)):
        name = _clean_name(f"{profile['name']} (copy {number})")
        number += 1
    return create_profile(db, profile["provider"], name, profile["description"], profile["settings"])


def delete_profile(db, profile_id) -> None:
    with db.transaction() as cursor:
        cursor.execute("DELETE FROM config_profile_targets WHERE profile_id=?", (int(profile_id),))
        cursor.execute("DELETE FROM config_server_profile_choice WHERE profile_id=?", (int(profile_id),))
        cursor.execute("DELETE FROM config_profiles WHERE id=?", (int(profile_id),))


def set_profile_targets(db, profile_id, server_ids=(), group_ids=()) -> None:
    profile = get_profile(db, profile_id)
    if not profile:
        raise ProfileError("config_profile_not_found")
    compatible = {int(row["id"]) for row in db.query(
        "SELECT id FROM servers WHERE LOWER(TRIM(type))=?", (profile["provider"],)) or []}
    groups = {int(row["id"]) for row in db.query("SELECT id FROM config_groups") or []}
    servers = sorted({int(value) for value in server_ids if str(value).isdigit()} & compatible)
    chosen_groups = sorted({int(value) for value in group_ids if str(value).isdigit()} & groups)
    with db.transaction() as cursor:
        cursor.execute("DELETE FROM config_profile_targets WHERE profile_id=?", (profile["id"],))
        cursor.executemany("INSERT INTO config_profile_targets VALUES (?, 'server', ?)",
                           [(profile["id"], server) for server in servers])
        cursor.executemany("INSERT INTO config_profile_targets VALUES (?, 'group', ?)",
                           [(profile["id"], group) for group in chosen_groups])


def profile_targets(db, profile_id) -> dict:
    rows = db.query("SELECT target_type, target_id FROM config_profile_targets WHERE profile_id=?",
                    (int(profile_id),)) or []
    return {
        "servers": {int(row["target_id"]) for row in rows if row["target_type"] == "server"},
        "groups": {int(row["target_id"]) for row in rows if row["target_type"] == "group"},
    }


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def list_groups(db) -> list[dict]:
    groups = [dict(row) for row in db.query("SELECT * FROM config_groups ORDER BY name COLLATE NOCASE") or []]
    members = {}
    for row in db.query("SELECT group_id, server_id FROM config_group_servers") or []:
        members.setdefault(int(row["group_id"]), set()).add(int(row["server_id"]))
    for group in groups:
        group["server_ids"] = members.get(int(group["id"]), set())
    return groups


def save_group(db, group_id, name, description, server_ids) -> int:
    name = _clean_name(name)
    if not name:
        raise ProfileError("config_group_name_required")
    if db.query_one("SELECT 1 FROM config_groups WHERE name=? COLLATE NOCASE AND id!=?", (name, int(group_id or 0))):
        raise ProfileError("config_group_name_taken")
    known = {int(row["id"]) for row in db.query(
        "SELECT id FROM servers WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')") or []}
    members = sorted({int(value) for value in server_ids if str(value).isdigit()} & known)
    description = _clean_name(description, DESCRIPTION_MAX_LENGTH)
    with db.transaction() as cursor:
        if group_id:
            cursor.execute("UPDATE config_groups SET name=?, description=? WHERE id=?", (name, description, int(group_id)))
            if not cursor.rowcount:
                raise ProfileError("config_group_not_found")
        else:
            cursor.execute("INSERT INTO config_groups(name, description) VALUES (?, ?)", (name, description))
            group_id = cursor.lastrowid
        cursor.execute("DELETE FROM config_group_servers WHERE group_id=?", (int(group_id),))
        cursor.executemany("INSERT INTO config_group_servers VALUES (?, ?)",
                           [(int(group_id), server) for server in members])
    return int(group_id)


def delete_group(db, group_id) -> None:
    with db.transaction() as cursor:
        cursor.execute("DELETE FROM config_profile_targets WHERE target_type='group' AND target_id=?", (int(group_id),))
        cursor.execute("DELETE FROM config_group_servers WHERE group_id=?", (int(group_id),))
        cursor.execute("DELETE FROM config_groups WHERE id=?", (int(group_id),))


# ---------------------------------------------------------------------------
# Profile resolution per server
# ---------------------------------------------------------------------------

def server_profiles(db) -> dict:
    """For each media server: assigned profiles, conflicts and the reference profile.

    A server gets the profiles assigned to it directly or through its groups,
    limited to its own platform. Two profiles conflict when they expect different
    values for the same setting. A conflict needs an explicit choice; until then
    the server has no reference profile.
    """
    servers = {int(row["id"]): dict(row) for row in db.query(
        """SELECT id, name, LOWER(TRIM(type)) AS type FROM servers
           WHERE LOWER(TRIM(type)) IN ('plex','jellyfin') ORDER BY name COLLATE NOCASE""") or []}
    profiles = {int(profile["id"]): profile for profile in list_profiles(db)}
    groups_of = {}
    for row in db.query("SELECT group_id, server_id FROM config_group_servers") or []:
        groups_of.setdefault(int(row["server_id"]), set()).add(int(row["group_id"]))
    assigned = {server_id: {} for server_id in servers}
    for row in db.query("SELECT profile_id, target_type, target_id FROM config_profile_targets") or []:
        profile = profiles.get(int(row["profile_id"]))
        if not profile:
            continue
        targets = ([int(row["target_id"])] if row["target_type"] == "server" else
                   [server for server, groups in groups_of.items() if int(row["target_id"]) in groups])
        for server_id in targets:
            if server_id in servers and servers[server_id]["type"] == profile["provider"]:
                assigned[server_id].setdefault(profile["id"], profile)
    choices = {int(row["server_id"]): int(row["profile_id"]) for row in db.query(
        "SELECT server_id, profile_id FROM config_server_profile_choice") or []}
    result = {}
    for server_id, server in servers.items():
        candidates = list(assigned[server_id].values())
        conflict_keys = sorted(_conflicting_keys(candidates))
        chosen = choices.get(server_id)
        reference = None
        if len(candidates) == 1:
            reference = candidates[0]
        elif candidates and not conflict_keys:
            reference = _merged_profile(candidates)
        elif chosen in assigned[server_id]:
            reference = assigned[server_id][chosen]
        result[server_id] = {
            "server": server,
            "profiles": candidates,
            "conflict_keys": conflict_keys,
            "needs_choice": bool(conflict_keys) and chosen not in assigned[server_id],
            "reference": reference,
        }
    return result


def _conflicting_keys(profiles) -> set:
    seen, conflicts = {}, set()
    for profile in profiles:
        for key, entry in profile["settings"].items():
            value = entry.get("value")
            if key in seen and seen[key] != value:
                conflicts.add(key)
            seen.setdefault(key, value)
    return conflicts


def _merged_profile(profiles) -> dict:
    settings = {}
    for profile in profiles:
        for key, entry in profile["settings"].items():
            settings.setdefault(key, entry)
    return {"id": None, "name": " + ".join(profile["name"] for profile in profiles),
            "provider": profiles[0]["provider"], "settings": settings}


def choose_server_profile(db, server_id, profile_id) -> None:
    resolved = server_profiles(db).get(int(server_id))
    if not resolved or int(profile_id) not in {int(p["id"]) for p in resolved["profiles"]}:
        raise ProfileError("config_profile_not_found")
    db.execute("""INSERT INTO config_server_profile_choice(server_id, profile_id) VALUES (?, ?)
                  ON CONFLICT(server_id) DO UPDATE SET profile_id=excluded.profile_id""",
               (int(server_id), int(profile_id)))


# ---------------------------------------------------------------------------
# Comparison matrix
# ---------------------------------------------------------------------------

def read_servers(db, server_ids) -> dict:
    """Read several servers in parallel; each answer is a result or an error key."""
    loaded, answers = {}, {}
    for server_id in server_ids:
        try:
            loaded[server_id] = load_media_server(db, server_id)
        except ServerConfigurationError as exc:
            answers[server_id] = {"error": str(exc)}

    def read(server_id):
        server, libraries = loaded[server_id]
        try:
            return server_id, read_loaded_server(server, libraries)
        except ServerConfigurationError as exc:
            return server_id, {"error": str(exc)}
        except Exception:
            from core.error_reporting import log_handled_failure
            log_handled_failure("server_configuration.compare_read", server_id=server_id)
            return server_id, {"error": "server_config_unexpected_answer"}

    if loaded:
        with ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(loaded)), thread_name_prefix="config-read") as pool:
            for server_id, answer in pool.map(read, list(loaded)):
                answers[server_id] = answer
    return answers


def _display(item) -> str:
    value = item.get("value")
    for choice in item.get("choices") or []:
        if str(choice.get("value")) == normalize_value(value):
            return str(choice.get("label") or value)
    return normalize_value(value)


def _library_name(name) -> str:
    return " ".join(str(name or "").lower().split())


def _merge_same_label(rows: dict, expected: dict) -> dict:
    """One line per setting: Plex can name the same setting differently on each server
    (for example a key that carries the GPU of the machine). Rows with the same label,
    category and library whose servers do not overlap are shown on a single line."""
    groups = {}
    for key, row in rows.items():
        group_key = (row["category"], _library_name(row.get("library")), str(row["label"]).strip().lower())
        groups.setdefault(group_key, []).append(key)
    merged = {}
    for keys in groups.values():
        first = rows[keys[0]]
        if len(keys) > 1 and not any(key in expected for key in keys):
            server_sets = [set(rows[key]["cells"]) for key in keys]
            if sum(len(servers) for servers in server_sets) == len(set().union(*server_sets)):
                for key in keys[1:]:
                    first["cells"].update(rows[key]["cells"])
                    first["advanced"] = first["advanced"] and rows[key]["advanced"]
                first["merged_keys"] = list(keys)
                merged[keys[0]] = first
                continue
        for key in keys:
            merged[key] = rows[key]
    return merged


def _choice_label(row, value) -> str:
    for choice in row.get("choices") or []:
        if str(choice.get("value")) == str(value):
            return str(choice.get("label") or value)
    return str(value)


def _recommend(row) -> None:
    """Recommended value from the Plex/Jellyfin documentation, otherwise the platform default."""
    row["recommended"] = None
    row["off_recommendation"] = False
    if row.get("library"):
        return
    entry = None
    for key in row.get("merged_keys") or [row["key"]]:
        entry = recommendations.recommendation_for(row.get("provider"), key, row["label"])
        if entry:
            break
    if entry:
        row["recommended"] = {"kind": "recommended", "value": entry["value"],
                              "display": _choice_label(row, entry["value"]),
                              "reason": entry["reason"], "source": entry["source"]}
        for cell in row["cells"].values():
            off = cell.get("display") is not None and not recommendations.follows(entry, cell.get("value"))
            cell["off_recommendation"] = off
            row["off_recommendation"] = row["off_recommendation"] or off
    elif row.get("default") is not None:
        row["recommended"] = {"kind": "default", "value": row["default"], "display": _choice_label(row, row["default"])}


def build_matrix(servers, answers, reference=None) -> dict:
    """Rows of settings x columns of servers, with differences and profile drift."""
    columns = []
    rows = {}
    for server in servers:
        answer = answers.get(server["id"]) or {"error": "server_config_unexpected_answer"}
        columns.append({"id": server["id"], "name": server["name"], "error": answer.get("error")})
        for item in answer.get("settings") or []:
            if item.get("sensitive"):
                continue
            key = item["compare_key"]
            row = rows.setdefault(key, {
                "key": key, "label": item.get("label") or key, "category": item.get("category") or "advanced",
                "library": item.get("library"), "advanced": bool(item.get("advanced")),
                "summary": item.get("summary") or "", "cells": {},
            })
            row["advanced"] = row["advanced"] and bool(item.get("advanced"))
            row["cells"][server["id"]] = {
                "value": normalize_value(item.get("value")), "display": _display(item), "key": key,
                "type": item.get("type") or "text", "choices": item.get("choices") or [],
                # Editable from the table (manual mode): written as is, never a secret or a task.
                "editable": bool(item.get("writable")) and item.get("source") != "scheduled_task",
            }
            if item.get("choices") and not row.get("choices"):
                row["choices"] = item["choices"]
            if item.get("default") is not None and row.get("default") is None:
                row["default"] = normalize_value(item["default"])
            row.setdefault("provider", server.get("type") or answer.get("provider"))
    expected = (reference or {}).get("settings") or {}
    rows = _merge_same_label(rows, expected)
    for key, entry in expected.items():
        rows.setdefault(key, {"key": key, "label": entry.get("label") or key, "category": entry.get("category") or "advanced",
                              "library": entry.get("library"), "advanced": False, "summary": "", "cells": {}})
    readable = [column["id"] for column in columns if not column["error"]]
    libraries_by_server = {}
    for row in rows.values():
        if row.get("library"):
            for server_id in row["cells"]:
                libraries_by_server.setdefault(server_id, set()).add(_library_name(row["library"]))
    result_rows = []
    drift_by_server = {column["id"]: 0 for column in columns}
    for row in rows.values():
        values = {row["cells"][server_id]["value"] if server_id in row["cells"] else None for server_id in readable}
        # Machine specific settings (name, port, paths...) differ by design: they are shown
        # as a normal, neutral difference and never counted as a deviation.
        row["machine_specific"] = bool(row.get("merged_keys")) or is_machine_specific(row["key"])
        # A library that only exists on some servers cannot be compared there.
        row["library_missing"] = bool(row.get("library")) and len(readable) > 1 and any(
            _library_name(row["library"]) not in libraries_by_server.get(server_id, set()) for server_id in readable)
        neutral = row["machine_specific"] or row["library_missing"]
        row["different"] = len(values) > 1 and not neutral
        row["varies"] = len(values) > 1 and row["machine_specific"] and not row["library_missing"]
        row["library_varies"] = len(values) > 1 and row["library_missing"]
        if key_entry := expected.get(row["key"]):
            row["expected"] = key_entry.get("value", "")
            row["expected_display"] = next((str(c.get("label")) for c in key_entry.get("choices") or []
                                            if str(c.get("value")) == row["expected"]), row["expected"])
            for server_id in readable:
                cell = row["cells"].get(server_id)
                status = "missing" if cell is None else ("ok" if cell["value"] == row["expected"] else "drift")
                row["cells"].setdefault(server_id, {"value": None, "display": None})["status"] = status
                if status != "ok":
                    drift_by_server[server_id] += 1
            row["drift"] = any(row["cells"][server_id].get("status") != "ok" for server_id in readable)
        else:
            row["expected"] = None
            row["drift"] = False
        _recommend(row)
        result_rows.append(row)
    order = {category: index for index, category in enumerate(CATEGORIES)}
    result_rows.sort(key=lambda row: (order.get(row["category"], 99), str(row.get("library") or ""), row["label"].lower()))
    for column in columns:
        column["drift"] = drift_by_server.get(column["id"], 0) if reference and not column["error"] else None
    return {
        "columns": columns,
        "rows": result_rows,
        "categories": [category for category in CATEGORIES if any(row["category"] == category for row in result_rows)],
        "different_count": sum(1 for row in result_rows if row["different"]),
        "machine_specific_count": sum(1 for row in result_rows if row["varies"]),
        "library_missing_count": sum(1 for row in result_rows if row["library_missing"]),
        "recommended_count": sum(1 for row in result_rows if (row["recommended"] or {}).get("kind") == "recommended"),
        "off_recommendation_count": sum(1 for row in result_rows if row["off_recommendation"]),
        "single": len(columns) == 1,
        "reference": reference,
    }
