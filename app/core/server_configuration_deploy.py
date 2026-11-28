"""Configuration Manager steps 4 and 5: previewed deployments and manual fixes.

Flow: plan (read-only preview, stored as a draft) -> confirm (the admin picks
the changes) -> apply, one server at a time -> verify by reading the server
again -> retry only what failed. Writes are allowed only in the "manual"
mode; the default mode is "monitoring" (no write at all). Auto remediation is
not implemented and can never be switched on from here.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from core import server_configuration_writer as writer
from core import server_configuration_dependencies as dependencies
from core import server_configuration_snapshots as snapshots
from core.server_configuration import ServerConfigurationError, load_media_server, read_loaded_server
from core.server_configuration_compliance import (
    ExceptionError, evaluate, read_scope, record_read, server_exceptions, set_exception,
)
from core.server_configuration_profiles import (
    MAX_COMPARED_SERVERS, ProfileError, get_profile, is_profile_eligible, list_groups, normalize_value,
    server_profiles, settings_from_read,
)
from logging_utils import get_logger

logger = get_logger("server_configuration")

MODES = ("monitoring", "manual")
DEFAULT_MODE = "monitoring"
MAX_DEPLOY_SERVERS = 50
DRAFT_TTL_HOURS = 24
READ_WORKERS = 4

# Not deployable unless the admin includes them explicitly: a wrong value can
# cut the server off the network or from remote clients.
RISKY_CATEGORIES = {"network", "remote_access"}
_RISKY_KEYS = re.compile(
    r"(port|remote|bind|lannetwork|localnetwork|proxy|https|secureconnection|certificate|relay|wan|upnp|"
    r"publish|allowednetworks|ipaddress|ipv4|ipv6|baseurl|autodiscovery)",
    re.IGNORECASE,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_manager_settings (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_deployments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK (kind IN ('deploy','fix')),
 source_name TEXT NOT NULL DEFAULT '',
 provider TEXT NOT NULL,
 include_risky INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'draft',
 created_at TEXT NOT NULL,
 confirmed_at TEXT,
 finished_at TEXT
);
CREATE TABLE IF NOT EXISTS config_deployment_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 deployment_id INTEGER NOT NULL REFERENCES config_deployments(id) ON DELETE CASCADE,
 server_id INTEGER NOT NULL,
 server_name TEXT NOT NULL DEFAULT '',
 compare_key TEXT NOT NULL,
 label TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT 'advanced',
 library TEXT,
 expected_value TEXT NOT NULL DEFAULT '',
 expected_display TEXT NOT NULL DEFAULT '',
 previous_value TEXT,
 previous_display TEXT,
 status TEXT NOT NULL,
 reason TEXT,
 error TEXT,
 attempts INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_config_deployment_items_deployment
 ON config_deployment_items(deployment_id, server_id);
"""

# Item statuses: excluded (shown, never applied), planned (preview), skipped
# (not chosen), pending (to apply), verified, failed.
_server_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


class DeployError(ValueError):
    """A request the admin must correct; the message is a translation key."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Mode and local exceptions
# ---------------------------------------------------------------------------

def get_mode(db) -> str:
    try:
        row = db.query_one("SELECT value FROM config_manager_settings WHERE key='mode'")
    except Exception:
        return DEFAULT_MODE
    return row["value"] if row and row["value"] in MODES else DEFAULT_MODE


def set_mode(db, mode) -> None:
    if mode not in MODES:
        raise DeployError("config_mode_invalid")
    db.execute("""INSERT INTO config_manager_settings(key, value) VALUES ('mode', ?)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (mode,))
    logger.info("Configuration manager mode set to %s", mode)


def require_manual(db) -> None:
    if get_mode(db) != "manual":
        raise DeployError("config_mode_monitoring_only")


# ---------------------------------------------------------------------------
# Plan (read-only preview)
# ---------------------------------------------------------------------------

def is_risky(entry) -> bool:
    if entry.get("category") in RISKY_CATEGORIES:
        return True
    setting = str(entry.get("key") or "").rsplit(".", 1)[-1]
    return bool(_RISKY_KEYS.search(setting))


def resolve_targets(db, provider, server_ids=(), group_ids=(), everyone=False) -> list[dict]:
    """Servers of the given platform chosen individually, by group, or all of them."""
    servers = {int(row["id"]): dict(row) for row in db.query(
        "SELECT id, name, LOWER(TRIM(type)) AS type, status FROM servers WHERE LOWER(TRIM(type))=? "
        "ORDER BY name COLLATE NOCASE", (provider,)) or []}
    wanted = set(servers) if everyone else {int(v) for v in server_ids if str(v).isdigit()} & set(servers)
    chosen_groups = {int(v) for v in group_ids if str(v).isdigit()}
    for group in list_groups(db):
        if int(group["id"]) in chosen_groups:
            wanted |= set(group["server_ids"]) & set(servers)
    return [servers[server_id] for server_id in servers if server_id in wanted]


def _read_targets(db, targets, references):
    """Read the targets in parallel (4 at a time); each answer is a result or an error key."""
    answers, jobs = {}, {}
    for server in targets:
        try:
            loaded, libraries = load_media_server(db, server["id"])
            libraries, sections = read_scope(loaded["type"], references[server["id"]], libraries)
            jobs[server["id"]] = (loaded, libraries, sections)
        except ServerConfigurationError as exc:
            answers[server["id"]] = {"error": str(exc)}

    def read(server_id):
        loaded, libraries, sections = jobs[server_id]
        try:
            return server_id, read_loaded_server(loaded, libraries, priority=True, sections=sections)
        except ServerConfigurationError as exc:
            return server_id, {"error": str(exc)}
        except Exception:
            from core.error_reporting import log_handled_failure
            log_handled_failure("server_configuration.deploy_preview", server_id=server_id)
            return server_id, {"error": "server_config_unexpected_answer"}

    if jobs:
        with ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(jobs)), thread_name_prefix="config-plan") as pool:
            answers.update(dict(pool.map(read, list(jobs))))
    return answers


def _choice_label(choices, value):
    for choice in choices or []:
        if str(choice.get("value")) == value:
            return str(choice.get("label") or value)
    return value


def _plan_items(server, reference, answer, *, include_risky, exceptions, only_keys=None, per_server=False):
    """Items for one server: changes to make and settings left out, with the reason."""
    if answer.get("error"):
        return [{"server_id": server["id"], "server_name": server["name"], "compare_key": "*", "label": "",
                 "category": "advanced", "library": None, "expected_value": "", "expected_display": "",
                 "previous_value": None, "previous_display": None, "status": "excluded",
                 "reason": answer["error"]}]
    actual = {item["compare_key"]: item for item in answer.get("settings") or []}
    items = []
    for key, entry in sorted((reference.get("settings") or {}).items()):
        if only_keys is not None and key not in only_keys:
            continue
        want = normalize_value(entry.get("value"))
        current = actual.get(key)
        item = {"server_id": server["id"], "server_name": server["name"], "compare_key": key,
                "label": entry.get("label") or key, "category": entry.get("category") or "advanced",
                "library": entry.get("library"), "expected_value": want,
                "expected_display": _choice_label(entry.get("choices"), want),
                "previous_value": None, "previous_display": None, "status": "planned", "reason": None}
        if current is not None:
            value = normalize_value(current.get("value"))
            item["previous_value"] = value
            item["previous_display"] = _choice_label(current.get("choices"), value)
            if value == want:
                continue  # Already as expected: nothing to do.
        reason = None
        if key in exceptions:
            reason = "config_reason_exception"
        elif current is None:
            reason = "config_reason_missing"
        elif not (is_editable(current) if per_server else is_profile_eligible(current)):
            reason = "config_reason_not_deployable"
        elif is_risky({**entry, "key": key}) and not include_risky:
            reason = "config_reason_risky"
        if reason:
            item.update(status="excluded", reason=reason)
        items.append(item)
    return items


def _cleanup_drafts(db) -> None:
    limit = (datetime.now(timezone.utc) - timedelta(hours=DRAFT_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cursor:
        cursor.execute("DELETE FROM config_deployment_items WHERE deployment_id IN "
                       "(SELECT id FROM config_deployments WHERE status='draft' AND created_at<?)", (limit,))
        cursor.execute("DELETE FROM config_deployments WHERE status='draft' AND created_at<?", (limit,))


def _store_plan(db, kind, source_name, provider, include_risky, items) -> int:
    _cleanup_drafts(db)
    now = _now()
    with db.transaction() as cursor:
        cursor.execute("""INSERT INTO config_deployments(kind, source_name, provider, include_risky, status, created_at)
                          VALUES (?,?,?,?,'draft',?)""", (kind, source_name, provider, int(bool(include_risky)), now))
        deployment_id = int(cursor.lastrowid)
        cursor.executemany(
            """INSERT INTO config_deployment_items(deployment_id, server_id, server_name, compare_key, label, category,
                   library, expected_value, expected_display, previous_value, previous_display, status, reason, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(deployment_id, i["server_id"], i["server_name"], i["compare_key"], i["label"], i["category"],
              i["library"], i["expected_value"], i["expected_display"], i["previous_value"], i["previous_display"],
              i["status"], i["reason"], now) for i in items])
    return deployment_id


def plan_deployment(db, source, *, server_ids=(), group_ids=(), everyone=False, include_risky=False,
                    keys=None) -> int:
    """Preview deploying a profile ("profile:<id>") or a server's settings ("server:<id>")."""
    source = str(source or "")
    if source.startswith("profile:") and source[8:].isdigit():
        reference = get_profile(db, int(source[8:]))
        if not reference:
            raise ProfileError("config_profile_not_found")
        provider, name, source_id = reference["provider"], reference["name"], None
    elif source.startswith("server:") and source[7:].isdigit():
        source_id = int(source[7:])
        try:
            loaded, libraries = load_media_server(db, source_id)
            read = read_loaded_server(loaded, libraries, priority=True)
        except ServerConfigurationError as exc:
            raise DeployError(str(exc)) from None
        settings, _ = settings_from_read(read)
        provider, name = loaded["type"], loaded["name"]
        reference = {"id": None, "name": name, "provider": provider, "settings": settings}
    else:
        raise DeployError("config_deploy_source_required")
    targets = [server for server in resolve_targets(db, provider, server_ids, group_ids, everyone)
               if server["id"] != source_id]
    if not targets:
        raise DeployError("config_deploy_targets_required")
    if len(targets) > MAX_DEPLOY_SERVERS:
        raise DeployError("config_deploy_too_many")
    wanted = None if not keys else {str(key) for key in keys}
    references = {server["id"]: reference for server in targets}
    answers = _read_targets(db, targets, references)
    exceptions = server_exceptions(db)
    items = []
    for server in targets:
        items += _plan_items(server, reference, answers[server["id"]], include_risky=include_risky,
                             exceptions=exceptions.get(server["id"], {}), only_keys=wanted)
    return _store_plan(db, "deploy", name, provider, include_risky, items)


MAX_EDITS = 200


def is_editable(item) -> bool:
    """A setting changed on one server from the comparison table: any writable value,
    including the server's own name or ports, but never a secret or a scheduled task."""
    return bool(item.get("writable")) and not item.get("sensitive") and item.get("source") != "scheduled_task"


def plan_edits(db, edits) -> int:
    """Preview changes typed in the comparison table: [{server_id, key, value}, ...]."""
    wanted = {}
    for edit in edits or []:
        if not isinstance(edit, dict) or not str(edit.get("server_id", "")).isdigit() or not edit.get("key"):
            raise DeployError("config_edit_invalid")
        value = edit.get("value")
        if value is None or isinstance(value, (dict, list)) or len(str(value)) > 1000:
            raise DeployError("config_edit_invalid")
        wanted.setdefault(int(edit["server_id"]), {})[str(edit["key"])] = normalize_value(value)
    if not wanted:
        raise DeployError("config_deploy_nothing_selected")
    if sum(len(keys) for keys in wanted.values()) > MAX_EDITS or len(wanted) > MAX_DEPLOY_SERVERS:
        raise DeployError("config_deploy_too_many")
    servers = {int(row["id"]): dict(row) for row in db.query(
        "SELECT id, name, LOWER(TRIM(type)) AS type FROM servers WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')") or []}
    if set(wanted) - set(servers):
        raise DeployError("config_deploy_targets_required")
    targets = [servers[server_id] for server_id in sorted(wanted)]
    references = {server_id: {"settings": {key: {"value": value} for key, value in keys.items()}}
                  for server_id, keys in wanted.items()}
    answers = _read_targets(db, targets, references)
    exceptions = server_exceptions(db)
    items = []
    for server in targets:
        answer = answers[server["id"]]
        actual = {item["compare_key"]: item for item in answer.get("settings") or []}
        # A setting Plex hides while another one turns it off: turn that one on first.
        unlocked = {}
        for key in list(wanted[server["id"]]):
            if key in actual:
                continue
            hidden = dependencies.hidden_by(server["type"], key, None, actual)
            if hidden and hidden["editable"]:
                unlocked[key] = hidden
                wanted[server["id"]].setdefault(hidden["parent_key"], normalize_value(hidden["enable"]))
        settings = {}
        for key, value in wanted[server["id"]].items():
            current = actual.get(key) or {}
            settings[key] = {"value": value, "label": current.get("label") or key,
                             "category": current.get("category") or "advanced",
                             "library": current.get("library"), "choices": current.get("choices") or []}
        planned = _plan_items(server, {"settings": settings}, answer, include_risky=True,
                              exceptions=exceptions.get(server["id"], {}), per_server=True)
        for item in planned:
            hidden = unlocked.get(item["compare_key"])
            if hidden and item["reason"] == "config_reason_missing":
                # Written after the setting it depends on (see _apply_server_locked).
                item.update(status="planned", reason=None, label=hidden["entry"]["label"],
                            category=hidden["parent_category"], previous_display=None)
        items += planned
    if not items:
        raise DeployError("config_edit_nothing_to_change")  # Every value typed is already in place.
    providers = "+".join(sorted({server["type"] for server in targets}))
    return _store_plan(db, "deploy", "Settings", providers, True, items)


def plan_fix(db, server_ids=None, keys=None) -> int:
    """Preview fixing deviations from each server's own reference profile (step 5)."""
    resolution = server_profiles(db)
    wanted = None if server_ids is None else {int(v) for v in server_ids if str(v).isdigit()}
    targets = [item for server_id, item in resolution.items()
               if item["reference"] and (wanted is None or server_id in wanted)]
    if not targets:
        raise DeployError("config_deploy_targets_required")
    providers = {item["server"]["type"] for item in targets}
    servers = [item["server"] for item in targets]
    references = {item["server"]["id"]: item["reference"] for item in targets}
    answers = _read_targets(db, servers, references)
    exceptions = server_exceptions(db)
    only = None if not keys else {str(key) for key in keys}
    items = []
    for server in servers:
        items += _plan_items(server, references[server["id"]], answers[server["id"]], include_risky=False,
                             exceptions=exceptions.get(server["id"], {}), only_keys=only)
    names = sorted({references[s["id"]]["name"] for s in servers})
    return _store_plan(db, "fix", ", ".join(names)[:200], "+".join(sorted(providers)), False, items)


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

def get_deployment(db, deployment_id) -> dict | None:
    row = db.query_one("SELECT * FROM config_deployments WHERE id=?", (int(deployment_id),))
    if not row:
        return None
    deployment = dict(row)
    items = [dict(item) for item in db.query(
        "SELECT * FROM config_deployment_items WHERE deployment_id=? ORDER BY server_name COLLATE NOCASE, server_id, "
        "category, library, label", (deployment["id"],)) or []]
    servers = {}
    for item in items:
        group = servers.setdefault(item["server_id"], {"id": item["server_id"], "name": item["server_name"],
                                                       "items": [], "error": None})
        if item["compare_key"] == "*":
            group["error"] = item["reason"]
            continue
        group["items"].append(item)
    for group in servers.values():
        statuses = [item["status"] for item in group["items"]]
        group["counts"] = {status: statuses.count(status) for status in
                           ("planned", "excluded", "skipped", "pending", "verified", "failed")}
        group["state"] = _server_state(group)
    deployment["servers"] = list(servers.values())
    deployment["counts"] = {status: sum(g["counts"][status] for g in servers.values())
                            for status in ("planned", "excluded", "skipped", "pending", "verified", "failed")}
    return deployment


def _server_state(group) -> str:
    counts = group["counts"]
    if group["error"]:
        return "error"
    if counts["pending"]:
        return "pending"
    if counts["failed"]:
        return "failed"
    if counts["verified"]:
        return "done"
    if counts["planned"]:
        return "planned"
    return "nothing"


def list_deployments(db, limit=20) -> list[dict]:
    rows = db.query("""SELECT d.*,
            SUM(CASE WHEN i.status='verified' THEN 1 ELSE 0 END) AS verified,
            SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN i.status='pending' THEN 1 ELSE 0 END) AS pending,
            COUNT(DISTINCT CASE WHEN i.compare_key!='*' THEN i.server_id END) AS servers
        FROM config_deployments d LEFT JOIN config_deployment_items i ON i.deployment_id=d.id
        WHERE d.status!='draft' GROUP BY d.id ORDER BY d.id DESC LIMIT ?""", (int(limit),)) or []
    return [dict(row) for row in rows]


def confirm_deployment(db, deployment_id, chosen_item_ids) -> None:
    """Keep the chosen planned changes, skip the others. Requires the manual mode."""
    require_manual(db)
    deployment = db.query_one("SELECT * FROM config_deployments WHERE id=?", (int(deployment_id),))
    if not deployment:
        raise DeployError("config_deploy_not_found")
    if deployment["status"] != "draft":
        raise DeployError("config_deploy_already_confirmed")
    chosen = {int(v) for v in chosen_item_ids if str(v).isdigit()}
    planned = {int(row["id"]) for row in db.query(
        "SELECT id FROM config_deployment_items WHERE deployment_id=? AND status='planned'", (int(deployment_id),)) or []}
    if not chosen & planned:
        raise DeployError("config_deploy_nothing_selected")
    now = _now()
    with db.transaction() as cursor:
        for item_id in planned:
            cursor.execute("UPDATE config_deployment_items SET status=?, updated_at=? WHERE id=?",
                           ("pending" if item_id in chosen else "skipped", now, item_id))
        cursor.execute("UPDATE config_deployments SET status='running', confirmed_at=? WHERE id=?",
                       (now, int(deployment_id)))
    logger.info("Configuration deployment %s confirmed: %s change(s)", deployment_id, len(chosen & planned))


def discard_draft(db, deployment_id) -> None:
    with db.transaction() as cursor:
        row = cursor.execute("SELECT status FROM config_deployments WHERE id=?", (int(deployment_id),)).fetchone()
        if row and row["status"] == "draft":
            cursor.execute("DELETE FROM config_deployment_items WHERE deployment_id=?", (int(deployment_id),))
            cursor.execute("DELETE FROM config_deployments WHERE id=?", (int(deployment_id),))


def retry_failed(db, deployment_id, server_id=None) -> int:
    require_manual(db)
    sql = "UPDATE config_deployment_items SET status='pending', error=NULL WHERE deployment_id=? AND status='failed'"
    params = [int(deployment_id)]
    if server_id is not None:
        sql += " AND server_id=?"
        params.append(int(server_id))
    count = db.execute(sql, tuple(params)).rowcount
    if count:
        db.execute("UPDATE config_deployments SET status='running', finished_at=NULL WHERE id=?", (int(deployment_id),))
    return count


def _lock_for(server_id) -> threading.Lock:
    with _locks_guard:
        return _server_locks.setdefault(int(server_id), threading.Lock())


def apply_server(db, deployment_id, server_id) -> dict:
    """Apply the pending changes of one server, then read it again to verify them."""
    require_manual(db)
    deployment = db.query_one("SELECT * FROM config_deployments WHERE id=?", (int(deployment_id),))
    if not deployment or deployment["status"] == "draft":
        raise DeployError("config_deploy_not_found")
    lock = _lock_for(server_id)
    if not lock.acquire(blocking=False):
        raise DeployError("config_deploy_server_busy")  # Never two writes on one server at once.
    try:
        return _apply_server_locked(db, int(deployment_id), int(server_id))
    finally:
        lock.release()
        _finish_if_done(db, int(deployment_id))


def _apply_server_locked(db, deployment_id, server_id) -> dict:
    items = [dict(row) for row in db.query(
        "SELECT * FROM config_deployment_items WHERE deployment_id=? AND server_id=? AND status='pending'",
        (deployment_id, server_id)) or []]
    if not items:
        return {"applied": 0, "verified": 0, "failed": 0}
    now = _now()
    try:
        server, libraries = load_media_server(db, server_id)
    except ServerConfigurationError as exc:
        _set_items(db, items, "failed", str(exc), now)
        return {"applied": 0, "verified": 0, "failed": len(items)}
    exceptions = server_exceptions(db, server_id).get(server_id, {})
    blocked = [item for item in items if item["compare_key"] in exceptions]
    _set_items(db, blocked, "failed", "config_reason_exception", now)
    items = [item for item in items if item["compare_key"] not in exceptions]
    # Settings hidden by another one (no previous value) are written once that one is changed.
    first = {item["compare_key"]: item["expected_value"] for item in items if item["previous_value"] is not None}
    then = {item["compare_key"]: item["expected_value"] for item in items if item["previous_value"] is None}
    results = writer.apply_changes(server, first, libraries) if first else {}
    if then:
        if any(error for error in results.values()):
            results.update({key: "config_deploy_dependency_failed" for key in then})
        else:
            results.update(writer.apply_changes(server, then, libraries))
    changes = {**first, **then}
    logger.info("Configuration deployment %s wrote %s setting(s) on server_id=%s", deployment_id,
                sum(1 for value in results.values() if value is None), server_id)
    # Verify: read the same settings back from the server.
    reference = {"settings": {item["compare_key"]: {"value": item["expected_value"], "label": item["label"],
                                                    "category": item["category"], "library": item["library"]}
                              for item in items}}
    scoped_libraries, sections = read_scope(server["type"], reference, libraries)
    try:
        read = read_loaded_server(server, scoped_libraries, priority=True, sections=sections)
    except ServerConfigurationError as exc:
        read = {"error": str(exc)}
    actual = {entry["compare_key"]: normalize_value(entry.get("value")) for entry in read.get("settings") or []}
    summary = {"applied": 0, "verified": 0, "failed": 0}
    with db.transaction() as cursor:
        for item in items:
            error = results.get(item["compare_key"])
            if error is None:
                summary["applied"] += 1
                if read.get("error"):
                    error = read["error"]
                elif actual.get(item["compare_key"]) != item["expected_value"]:
                    error = "config_deploy_not_applied"
            status = "failed" if error else "verified"
            summary[status] += 1
            cursor.execute("""UPDATE config_deployment_items SET status=?, error=?, attempts=attempts+1, updated_at=?
                              WHERE id=?""", (status, error, now, item["id"]))
    if not read.get("error"):
        record_read(db, server_id, read)  # Refresh compliance with what was just read.
        snapshots.merge_read(db, server_id, read)  # And the values shown in the Settings view.
    return summary


def _set_items(db, items, status, error, now):
    with db.transaction() as cursor:
        for item in items:
            cursor.execute("""UPDATE config_deployment_items SET status=?, error=?, attempts=attempts+1, updated_at=?
                              WHERE id=?""", (status, error, now, item["id"]))


def _finish_if_done(db, deployment_id) -> None:
    row = db.query_one("""SELECT SUM(status='pending') AS pending, SUM(status='failed') AS failed,
                                 SUM(status='verified') AS verified
                          FROM config_deployment_items WHERE deployment_id=?""", (deployment_id,))
    if row and not int(row["pending"] or 0):
        status = "partial" if int(row["failed"] or 0) and int(row["verified"] or 0) else \
            ("failed" if int(row["failed"] or 0) else "done")
        db.execute("UPDATE config_deployments SET status=?, finished_at=? WHERE id=? AND status='running'",
                   (status, _now(), deployment_id))


__all__ = [
    "DeployError", "MODES", "get_mode", "set_mode", "server_exceptions", "set_exception", "plan_deployment",
    "plan_fix", "get_deployment", "list_deployments", "confirm_deployment", "discard_draft", "retry_failed",
    "apply_server", "is_risky", "resolve_targets", "MAX_COMPARED_SERVERS", "evaluate",
]
