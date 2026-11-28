"""Configuration Manager step 3: compliance of servers with their reference profile.

Read-only on Plex and Jellyfin. A check reads only what the reference profile
needs, compares it with the expected values and keeps, per server, the latest
result plus the last observed value of each referenced setting. Nothing else
is historised: a short list of values changed directly on a server is kept for
traceability, and an unchanged set of deviations is reported only once.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from core.server_configuration import (
    JELLYFIN_SECTIONS, READ_BUDGET_SECONDS, ServerConfigurationError, load_media_server, read_loaded_server,
)
from core import server_configuration_snapshots as snapshots
from core.server_configuration_profiles import normalize_value, server_profiles
from logging_utils import get_logger

logger = get_logger("server_configuration")

SCHEDULED_BUDGET_SECONDS = 90
MANUAL_BUDGET_SECONDS = 120
READ_WORKERS = 4
MIN_SERVER_BUDGET_SECONDS = 5
CHANGES_KEPT_PER_SERVER = 50

STATUSES = ("compliant", "non_compliant", "partial", "unreachable", "not_checked", "outdated", "conflict", "unmanaged")
# Summary buckets shown at the top of the page.
SUMMARY = {
    "compliant": "compliant", "non_compliant": "non_compliant", "unreachable": "unreachable",
    "partial": "not_checked", "not_checked": "not_checked", "outdated": "not_checked", "conflict": "not_checked",
    "unmanaged": "unmanaged",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_compliance (
 server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
 profile_id INTEGER,
 profile_name TEXT NOT NULL DEFAULT '',
 reference_hash TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL,
 drift_count INTEGER NOT NULL DEFAULT 0,
 unverified_count INTEGER NOT NULL DEFAULT 0,
 checked_count INTEGER NOT NULL DEFAULT 0,
 drift_json TEXT NOT NULL DEFAULT '[]',
 observed_json TEXT NOT NULL DEFAULT '{}',
 signature TEXT NOT NULL DEFAULT '',
 error TEXT,
 checked_at TEXT NOT NULL,
 drift_since TEXT
);
CREATE TABLE IF NOT EXISTS config_compliance_changes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
 compare_key TEXT NOT NULL,
 label TEXT NOT NULL DEFAULT '',
 library TEXT,
 previous_value TEXT,
 current_value TEXT,
 detected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_server_exceptions (
 server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
 compare_key TEXT NOT NULL,
 label TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 PRIMARY KEY (server_id, compare_key)
);
CREATE INDEX IF NOT EXISTS idx_config_compliance_changes_server
 ON config_compliance_changes(server_id, detected_at);
""" + snapshots.SCHEMA  # The Settings view reads the last snapshot of each server.


class ExceptionError(ValueError):
    """A request the admin must correct; the message is a translation key."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _json(raw, default):
    try:
        value = json.loads(raw) if raw else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


# Local exceptions: settings a server keeps on purpose. They are never counted
# as deviations and never deployed to that server.
def server_exceptions(db, server_id=None) -> dict:
    """{server_id: {compare_key: label}}"""
    sql, params = "SELECT * FROM config_server_exceptions", ()
    if server_id is not None:
        sql, params = sql + " WHERE server_id=?", (int(server_id),)
    result = {}
    try:
        rows = db.query(sql, params) or []
    except Exception:
        return result
    for row in rows:
        result.setdefault(int(row["server_id"]), {})[row["compare_key"]] = row["label"]
    return result


def set_exception(db, server_id, compare_key, label="", *, enabled=True) -> None:
    compare_key = str(compare_key or "").strip()[:300]
    if not compare_key or not db.query_one(
            "SELECT 1 FROM servers WHERE id=? AND LOWER(TRIM(type)) IN ('plex','jellyfin')", (int(server_id),)):
        raise ExceptionError("config_exception_invalid")
    if enabled:
        db.execute("""INSERT INTO config_server_exceptions(server_id, compare_key, label, created_at) VALUES (?,?,?,?)
                      ON CONFLICT(server_id, compare_key) DO NOTHING""",
                   (int(server_id), compare_key, str(label or "")[:200], _now()))
    else:
        db.execute("DELETE FROM config_server_exceptions WHERE server_id=? AND compare_key=?",
                   (int(server_id), compare_key))



def reference_hash(reference) -> str:
    expected = {key: entry.get("value") for key, entry in ((reference or {}).get("settings") or {}).items()}
    return hashlib.sha1(json.dumps(expected, sort_keys=True).encode("utf-8")).hexdigest()


def _library_name(key: str):
    if key.startswith("library[") and "]." in key:
        return key[len("library["):key.index("].")]
    return None


def read_scope(provider, reference, libraries):
    """Only the reads the reference profile needs: (libraries, jellyfin sections)."""
    keys = list(((reference or {}).get("settings") or {}).keys())
    wanted_libraries = {_library_name(key) for key in keys} - {None}
    if provider == "plex":
        chosen = [library for library in libraries or ()
                  if " ".join(str(library.get("name") or "").lower().split()) in wanted_libraries]
        return chosen, None
    sections = {key.split(".", 1)[0] for key in keys if "." in key and not key.startswith("library[")}
    sections = {section for section in sections if section in JELLYFIN_SECTIONS}
    if wanted_libraries:
        sections.add("libraries")
    return (), sections


def _choice_label(choices, value):
    for choice in choices or []:
        if str(choice.get("value")) == value:
            return str(choice.get("label") or value)
    return value


def _library_of(key, entry):
    """Normalized library name of a library setting, None for a server setting."""
    if str(key).startswith("library["):
        return str(key)[len("library["):].split("]", 1)[0]
    name = (entry or {}).get("library")
    return " ".join(str(name).lower().split()) if name else None


def evaluate(reference, result, exceptions=()) -> dict:
    """Compare a server read with the expected values of its reference profile."""
    expected = {key: entry for key, entry in ((reference or {}).get("settings") or {}).items()
                if key not in set(exceptions or ())}
    actual = {item["compare_key"]: item for item in result.get("settings") or [] if not item.get("sensitive")}
    incomplete = bool(result.get("errors"))
    # A library the server does not have is not a deviation: its settings do not apply there.
    present_libraries = {_library_of(key, item) for key, item in actual.items()} - {None}
    if not incomplete:  # When part of the server could not be read, the library may just be unread.
        expected = {key: entry for key, entry in expected.items()
                    if _library_of(key, entry) in present_libraries | {None}}
    drifts, observed, unverified = [], {}, 0
    for key, entry in sorted(expected.items()):
        want = normalize_value(entry.get("value"))
        item = actual.get(key)
        base = {"key": key, "label": entry.get("label") or key, "category": entry.get("category") or "advanced",
                "library": entry.get("library"), "expected": want,
                "expected_display": _choice_label(entry.get("choices"), want)}
        if item is None:
            if incomplete:
                unverified += 1  # Part of the server could not be read: no verdict.
                continue
            drifts.append({**base, "actual": None, "actual_display": None, "missing": True, "writable": False})
            continue
        value = normalize_value(item.get("value"))
        observed[key] = value
        if value != want:
            drifts.append({**base, "actual": value, "actual_display": _choice_label(item.get("choices"), value),
                           "missing": False, "writable": bool(item.get("writable"))})
    status = "non_compliant" if drifts else ("partial" if unverified else "compliant")
    signature = hashlib.sha1(json.dumps([(d["key"], d["actual"]) for d in drifts]).encode("utf-8")).hexdigest() \
        if drifts else ""
    return {"status": status, "drifts": drifts, "observed": observed, "unverified": unverified,
            "checked": len(expected) - unverified, "signature": signature}


def _store_result(db, server, reference, outcome, now) -> dict:
    previous = db.query_one("SELECT * FROM config_compliance WHERE server_id=?", (server["id"],))
    previous = dict(previous) if previous else {}
    old_observed = _json(previous.get("observed_json"), {})
    labels = {key: entry for key, entry in reference["settings"].items()}
    changes = [(key, old_observed[key], value) for key, value in outcome["observed"].items()
               if key in old_observed and old_observed[key] != value]
    observed = {**old_observed, **outcome["observed"]}
    observed = {key: value for key, value in observed.items() if key in labels}
    same_drifts = bool(outcome["signature"]) and previous.get("signature") == outcome["signature"]
    drift_since = previous.get("drift_since") if same_drifts else (now if outcome["drifts"] else None)
    with db.transaction() as cursor:
        cursor.execute(
            """INSERT INTO config_compliance(server_id, profile_id, profile_name, reference_hash, status, drift_count,
                   unverified_count, checked_count, drift_json, observed_json, signature, error, checked_at, drift_since)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)
               ON CONFLICT(server_id) DO UPDATE SET profile_id=excluded.profile_id,
                   profile_name=excluded.profile_name, reference_hash=excluded.reference_hash,
                   status=excluded.status, drift_count=excluded.drift_count,
                   unverified_count=excluded.unverified_count, checked_count=excluded.checked_count,
                   drift_json=excluded.drift_json, observed_json=excluded.observed_json,
                   signature=excluded.signature, error=NULL, checked_at=excluded.checked_at,
                   drift_since=excluded.drift_since""",
            (server["id"], reference.get("id"), reference.get("name") or "", reference_hash(reference),
             outcome["status"], len(outcome["drifts"]), outcome["unverified"], outcome["checked"],
             json.dumps(outcome["drifts"], ensure_ascii=False), json.dumps(observed, ensure_ascii=False),
             outcome["signature"], now, drift_since),
        )
        cursor.executemany(
            """INSERT INTO config_compliance_changes(server_id, compare_key, label, library, previous_value,
                   current_value, detected_at) VALUES (?,?,?,?,?,?,?)""",
            [(server["id"], key, labels[key].get("label") or key, labels[key].get("library"), old, new, now)
             for key, old, new in changes],
        )
        if changes:
            cursor.execute(
                """DELETE FROM config_compliance_changes WHERE server_id=? AND id NOT IN (
                       SELECT id FROM config_compliance_changes WHERE server_id=? ORDER BY id DESC LIMIT ?)""",
                (server["id"], server["id"], CHANGES_KEPT_PER_SERVER),
            )
    new_drifts = outcome["signature"] != (previous.get("signature") or "")
    if new_drifts and outcome["drifts"]:
        logger.warning("Configuration drift on server_id=%s profile=%s: %s setting(s) differ from the profile",
                       server["id"], reference.get("name"), len(outcome["drifts"]))
    elif new_drifts and previous.get("signature"):
        logger.info("Configuration back in line with the profile on server_id=%s", server["id"])
    for key, old, new in changes:
        logger.info("Setting changed on the server: server_id=%s key=%s", server["id"], key)
    return {"changes": len(changes), "new_drifts": new_drifts and bool(outcome["drifts"])}


def _store_error(db, server, reference, error, now) -> None:
    db.execute(
        """INSERT INTO config_compliance(server_id, profile_id, profile_name, reference_hash, status, error, checked_at)
           VALUES (?,?,?,?,'unreachable',?,?)
           ON CONFLICT(server_id) DO UPDATE SET status='unreachable', error=excluded.error,
               checked_at=excluded.checked_at, profile_id=excluded.profile_id,
               profile_name=excluded.profile_name, reference_hash=excluded.reference_hash""",
        (server["id"], reference.get("id"), reference.get("name") or "", reference_hash(reference), error, now),
    )


def check_compliance(db, server_ids=None, *, scheduled=False, budget_seconds=None) -> dict:
    """Check the servers that have a reference profile. Returns a short summary.

    scheduled=True is the periodic run: servers not online are recorded as
    unreachable without being called, and Plex reads queue behind interactive
    requests. Reads run in parallel with an overall time budget, so one slow
    server cannot hold up the others for long.
    """
    budget = budget_seconds or (SCHEDULED_BUDGET_SECONDS if scheduled else MANUAL_BUDGET_SECONDS)
    deadline = time.monotonic() + budget
    wanted = None if server_ids is None else {int(server_id) for server_id in server_ids}
    resolution = server_profiles(db)
    targets = {server_id: item for server_id, item in resolution.items()
               if item["reference"] and (wanted is None or server_id in wanted)}
    summary = {"checked": 0, "compliant": 0, "non_compliant": 0, "partial": 0, "unreachable": 0,
               "skipped": 0, "changes": 0, "new_drifts": 0}
    if not targets:
        return summary
    online = {int(row["id"]): str(row["status"] or "") for row in db.query("SELECT id, status FROM servers") or []}
    now = _now()
    jobs = {}
    for server_id, item in targets.items():
        reference = item["reference"]
        if scheduled and online.get(server_id) != "up":
            _store_error(db, item["server"], reference, "server_config_unreachable", now)
            summary["unreachable"] += 1
            continue
        try:
            server, libraries = load_media_server(db, server_id)
        except ServerConfigurationError as exc:
            _store_error(db, item["server"], reference, str(exc), now)
            summary["unreachable"] += 1
            continue
        libraries, sections = read_scope(server["type"], reference, libraries)
        jobs[server_id] = (server, libraries, sections, reference)

    def read(server_id):
        server, libraries, sections, _ = jobs[server_id]
        remaining = deadline - time.monotonic()
        if remaining < MIN_SERVER_BUDGET_SECONDS:
            return server_id, None
        try:
            return server_id, read_loaded_server(server, libraries, priority=not scheduled, sections=sections,
                                                 budget_seconds=min(READ_BUDGET_SECONDS, remaining))
        except ServerConfigurationError as exc:
            return server_id, {"error": str(exc)}
        except Exception:
            from core.error_reporting import log_handled_failure
            log_handled_failure("server_configuration.compliance_read", server_id=server_id)
            return server_id, {"error": "server_config_unexpected_answer"}

    exceptions = server_exceptions(db)
    answers = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(jobs)), thread_name_prefix="config-check") as pool:
            answers = dict(pool.map(read, list(jobs)))
    now = _now()
    for server_id, answer in answers.items():
        server, _, _, reference = jobs[server_id]
        if answer is None:
            summary["skipped"] += 1  # Budget spent: keep the previous result for the next run.
            continue
        if answer.get("error"):
            _store_error(db, server, reference, answer["error"], now)
            summary["unreachable"] += 1
            continue
        outcome = evaluate(reference, answer, exceptions.get(server_id, {}))
        stored = _store_result(db, server, reference, outcome, now)
        snapshots.merge_read(db, server_id, answer)
        summary["checked"] += 1
        summary[outcome["status"]] += 1
        summary["changes"] += stored["changes"]
        summary["new_drifts"] += int(stored["new_drifts"])
    return summary


def record_read(db, server_id, result) -> None:
    """Store compliance from a read made elsewhere (after a deployment), without reading again."""
    item = server_profiles(db).get(int(server_id))
    if not item or not item["reference"] or result.get("error"):
        return
    exceptions = server_exceptions(db, server_id).get(int(server_id), {})
    reference = item["reference"]
    keys = set(reference["settings"]) - set(exceptions)
    read_keys = {entry["compare_key"] for entry in result.get("settings") or []}
    if not keys <= read_keys:
        return  # Partial read (only the deployed settings): wait for the next full check.
    _store_result(db, item["server"], reference, evaluate(reference, result, exceptions), _now())


def run_scheduled_compliance(db):
    """Called by check_servers. Costs nothing when no profile is assigned."""
    try:
        row = db.query_one("SELECT COUNT(*) AS n FROM config_profile_targets")
    except Exception:
        return None  # Tables not created yet.
    if not row or not int(row["n"] or 0):
        return None
    return check_compliance(db, scheduled=True)


def compliance_overview(db) -> dict:
    """Per server status, per setting view and recent changes, for the page."""
    resolution = server_profiles(db)
    stored = {int(row["server_id"]): dict(row) for row in db.query("SELECT * FROM config_compliance") or []}
    exceptions = server_exceptions(db)
    servers = []
    by_setting = {}
    for server_id, item in resolution.items():
        row = stored.get(server_id)
        reference = item["reference"]
        entry = {"server": item["server"], "profiles": item["profiles"], "reference": reference,
                 "conflict_keys": item["conflict_keys"], "drifts": [], "drift_count": 0, "checked_at": None,
                 "error": None, "drift_since": None, "unverified_count": 0, "checked_count": 0}
        if not item["profiles"]:
            entry["status"] = "unmanaged"
        elif item["needs_choice"]:
            entry["status"] = "conflict"
        elif not row:
            entry["status"] = "not_checked"
        else:
            entry.update(status=row["status"], checked_at=row["checked_at"], error=row["error"],
                         drift_since=row["drift_since"], drifts=_json(row["drift_json"], []),
                         drift_count=int(row["drift_count"] or 0), unverified_count=int(row["unverified_count"] or 0),
                         checked_count=int(row["checked_count"] or 0))
            if row["reference_hash"] != reference_hash(reference):
                entry["status"] = "outdated"
        entry["exceptions"] = exceptions.get(server_id, {})
        if entry["exceptions"] and entry["drifts"]:
            entry["drifts"] = [d for d in entry["drifts"] if d["key"] not in entry["exceptions"]]
            entry["drift_count"] = len(entry["drifts"])
            if entry["status"] == "non_compliant" and not entry["drifts"]:
                entry["status"] = "partial" if entry["unverified_count"] else "compliant"
        if entry["status"] == "non_compliant":
            for drift in entry["drifts"]:
                setting = by_setting.setdefault(drift["key"], {**{k: drift[k] for k in (
                    "key", "label", "category", "library", "expected_display")}, "servers": []})
                setting["servers"].append({"id": server_id, "name": item["server"]["name"],
                                           "actual_display": drift["actual_display"], "missing": drift["missing"]})
        servers.append(entry)
    counts = {bucket: 0 for bucket in ("compliant", "non_compliant", "not_checked", "unreachable", "unmanaged")}
    for entry in servers:
        counts[SUMMARY[entry["status"]]] += 1
    names = {server_id: item["server"]["name"] for server_id, item in resolution.items()}
    changes = []
    for row in db.query("SELECT * FROM config_compliance_changes ORDER BY id DESC LIMIT 20") or []:
        change = dict(row)
        if int(change["server_id"]) in names:
            change["server_name"] = names[int(change["server_id"])]
            changes.append(change)
    order = {"non_compliant": 0, "unreachable": 1, "conflict": 2, "outdated": 3, "partial": 4, "not_checked": 5,
             "compliant": 6, "unmanaged": 7}
    servers.sort(key=lambda entry: (order.get(entry["status"], 9), str(entry["server"]["name"]).lower()))
    settings = sorted(by_setting.values(), key=lambda s: (-len(s["servers"]), str(s["label"]).lower()))
    return {"servers": servers, "counts": counts, "settings": settings, "changes": changes,
            "managed": sum(1 for entry in servers if entry["status"] != "unmanaged")}
