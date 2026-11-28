"""Settings view of the Compliance pages: one line per setting, whatever the number of servers.

Each line shows how the servers of the chosen scope are spread over the values of
the setting (for example "Automatic x15, Fast x3"), the recommended value, and how
many servers are off their own reference profile. It works from the last snapshot
of each server (core.server_configuration_snapshots), never by calling every
server while the page loads.
"""

from __future__ import annotations

from core import server_configuration_dependencies as dependencies
from core import server_configuration_snapshots as snapshots
from core.server_configuration_compliance import server_exceptions
from core.server_configuration_profiles import build_matrix, list_groups, normalize_value, server_profiles

PROVIDERS = ("plex", "jellyfin")
CHIPS = 3  # Values shown on the line; the others are counted as "+N".


def media_servers(db) -> list[dict]:
    return [dict(row) for row in db.query(
        """SELECT id, name, LOWER(TRIM(type)) AS type, status FROM servers
           WHERE LOWER(TRIM(type)) IN ('plex','jellyfin') ORDER BY name COLLATE NOCASE, id""") or []]


def resolve_scope(db, provider=None, group_id=None, server_ids=None) -> dict:
    """The servers of one platform to show: all of them, one group, or a selection."""
    servers = media_servers(db)
    counts = {name: sum(1 for server in servers if server["type"] == name) for name in PROVIDERS}
    available = [name for name in PROVIDERS if counts[name]]
    chosen_ids = {int(value) for value in server_ids or () if str(value).isdigit()}
    if provider not in available:
        picked = [server for server in servers if server["id"] in chosen_ids]
        provider = picked[0]["type"] if picked else (max(available, key=lambda name: counts[name]) if available else None)
    platform = [server for server in servers if server["type"] == provider]
    groups = [group for group in list_groups(db) if set(group["server_ids"]) & {s["id"] for s in platform}]
    group = next((g for g in groups if str(g["id"]) == str(group_id)), None) if group_id else None
    if group:
        chosen = [server for server in platform if server["id"] in set(group["server_ids"])]
        kind = "group"
    elif chosen_ids & {server["id"] for server in platform}:
        chosen = [server for server in platform if server["id"] in chosen_ids]
        kind = "servers"
    else:
        chosen = platform
        kind = "all"
    return {"provider": provider, "available": available, "counts": counts, "platform": platform,
            "groups": groups, "group": group, "kind": kind, "servers": chosen}


def _answers(db, servers):
    stored = snapshots.load(db, [server["id"] for server in servers])
    answers, state = {}, {}
    for server in servers:
        snap = stored.get(server["id"])
        if not snap or (not snap["settings"] and snap["error"]):
            error = (snap or {}).get("error") or "config_snapshot_missing"
            answers[server["id"]] = {"error": error, "provider": server["type"]}
        else:
            answers[server["id"]] = {"settings": snap["settings"], "provider": server["type"]}
        state[server["id"]] = {"read_at": (snap or {}).get("read_at"), "error": (snap or {}).get("error"),
                               "missing": snap is None}
    return answers, state


def build(db, servers, *, only_key=None) -> dict:
    """Lines of the Settings view for these servers (one platform)."""
    answers, state = _answers(db, servers)
    matrix = build_matrix(servers, answers)
    names = {server["id"]: server["name"] for server in servers}
    readable = [column["id"] for column in matrix["columns"] if not column["error"]]
    references = {server_id: item["reference"] for server_id, item in server_profiles(db).items()
                  if item["reference"] and server_id in names}
    exceptions = server_exceptions(db)
    by_server = {server_id: {item.get("compare_key") or item.get("key"): item
                             for item in (answer.get("settings") or [])}
                 for server_id, answer in answers.items()}
    provider = servers[0]["type"] if servers else ""
    rows = []
    for row in matrix["rows"]:
        if only_key is not None and row["key"] != only_key:
            continue
        rows.append(_line(row, readable, names, references, exceptions, by_server, provider))
    summary = {
        "settings": len(rows),
        "different": sum(1 for row in rows if row["state"] == "different"),
        "off_profile": sum(1 for row in rows if row["off_profile"]),
        "off_recommendation": sum(1 for row in rows if row["off_recommendation"]),
    }
    servers_state = [{**server, **state[server["id"]],
                      "error": next((c["error"] for c in matrix["columns"] if c["id"] == server["id"]), None)
                      or state[server["id"]]["error"]} for server in servers]
    return {"rows": rows, "summary": summary, "categories": matrix["categories"], "servers": servers_state,
            "readable": len(readable),
            # "Different from profile" is only offered when a server of the scope has one.
            "profiled": bool(references),
            "missing_ids": [server["id"] for server in servers if state[server["id"]]["missing"]],
            "oldest_read": min((s["read_at"] for s in state.values() if s["read_at"]), default=None)}


def _line(row, readable, names, references, exceptions, by_server=None, provider="") -> dict:
    groups = {}
    off_profile = 0
    expected_values = set()
    editable = None
    for server_id in readable:
        cell = row["cells"].get(server_id)
        value = cell["value"] if cell and cell.get("display") is not None else None
        key = (cell or {}).get("key") or row["key"]
        reference = references.get(server_id)
        entry = ((reference or {}).get("settings") or {}).get(key)
        expected = normalize_value(entry.get("value")) if entry else None
        missing_library = value is None and bool(row.get("library"))  # Not on this server: not a deviation.
        is_off = bool(entry) and not missing_library and key not in exceptions.get(server_id, {}) and value != expected
        if entry:
            expected_values.add(expected)
        off_profile += int(is_off)
        if cell and cell.get("editable") and editable is None:
            editable = {"type": cell.get("type") or "text", "choices": cell.get("choices") or []}
        group = groups.setdefault(value, {"value": value, "display": None if value is None else cell["display"],
                                          "servers": []})
        hidden = None
        if value is None and not row.get("library"):
            # Plex hides some settings while another one turns them off: say so, and allow
            # changing it (the setting it depends on is turned on in the same preview).
            hidden = dependencies.hidden_by(provider, key, row["label"], (by_server or {}).get(server_id))
            if hidden:
                hidden = {k: v for k, v in hidden.items() if k != "entry"}
        group["servers"].append({
            "id": server_id, "name": names[server_id], "key": key,
            "editable": bool(cell and cell.get("editable")) or bool(hidden and hidden["editable"]),
            "hidden_by": hidden,
            "off_profile": is_off, "expected": expected,
            "expected_display": _expected_display(row, {expected}) if entry else None,
            "off_recommendation": bool(cell and cell.get("off_recommendation")),
            # Kept as a local exception: shown in the panel, where it can be removed.
            "exception": key in exceptions.get(server_id, {}),
        })
    # Values with servers off their profile come first, then the most common ones.
    ordered = sorted(groups.values(), key=lambda g: (g["value"] is None, not any(s["off_profile"] for s in g["servers"]),
                                                     -len(g["servers"]), str(g["display"])))
    by_count = sorted(groups.values(), key=lambda g: (g["value"] is None, -len(g["servers"]), str(g["display"])))
    present = [group for group in ordered if group["value"] is not None]
    if row.get("library_missing"):
        state = "library"
    elif row.get("machine_specific") and len(present) > 1:
        state = "specific"
    elif len(ordered) > 1:
        state = "different"
    else:
        state = "same"
    recommended = row.get("recommended")
    return {
        "key": row["key"], "label": row["label"], "category": row["category"], "library": row.get("library"),
        "summary": row.get("summary") or "", "advanced": row.get("advanced"), "merged": bool(row.get("merged_keys")),
        "state": state, "groups": ordered, "chips": by_count[:CHIPS], "more": max(0, len(ordered) - CHIPS),
        "servers": len(readable), "off_profile": off_profile,
        "expected": next(iter(expected_values)) if len(expected_values) == 1 else None,
        "expected_display": _expected_display(row, expected_values),
        "recommended": recommended,
        "off_recommendation": sum(1 for g in ordered for s in g["servers"] if s["off_recommendation"]),
        "editable": editable,
        "exceptions": sum(1 for g in ordered for s in g["servers"] if s["exception"]),
    }


def _expected_display(row, values):
    if len(values) != 1:
        return None
    value = next(iter(values))
    for choice in row.get("choices") or []:
        if str(choice.get("value")) == value:
            return str(choice.get("label") or value)
    return value


def overview(db) -> dict:
    """Overview tab: one line per server with its state, profile, groups and last reads."""
    from core.server_configuration_compliance import compliance_overview

    data = compliance_overview(db)
    groups_by_server = {}
    for group in list_groups(db):
        for server_id in group["server_ids"]:
            groups_by_server.setdefault(int(server_id), []).append({"id": group["id"], "name": group["name"]})
    ids = [entry["server"]["id"] for entry in data["servers"]]
    stored = snapshots.load(db, ids)
    for entry in data["servers"]:
        server_id = entry["server"]["id"]
        entry["groups"] = groups_by_server.get(server_id, [])
        snap = stored.get(server_id) or {}
        entry["read_at"] = snap.get("read_at")
        entry["read_error"] = snap.get("error")
    data["providers"] = sorted({entry["server"]["type"] for entry in data["servers"]})
    data["managed_ids"] = [entry["server"]["id"] for entry in data["servers"] if entry["status"] != "unmanaged"]
    return data
