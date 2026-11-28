"""Read Plex and Jellyfin server settings for the Server Configuration page.

Step 1 of the Configuration Manager is read-only: settings are read live from
the server when an administrator asks for them, normalized into one list and
grouped in VODUM categories. Nothing is written to Plex or Jellyfin and nothing
is stored. Secrets and personal identifiers are masked before leaving this
module.
"""

from __future__ import annotations

import json
import re
import time

from core.http_security import server_http_session
from core.jellyfin_auth import jellyfin_headers
from core.monitoring.resource_stats import candidate_bases
from core.plex_rate_limit import wait_for_plex_slot
from logging_utils import get_logger

logger = get_logger("server_configuration")

CATEGORIES = (
    "general", "network", "remote_access", "transcoding", "streaming", "libraries",
    "metadata", "subtitles", "scheduled_tasks", "security", "advanced",
)
READ_BUDGET_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 10
MASK = "••••••"
JELLYFIN_NAMED_CONFIGURATIONS = (
    ("encoding", "transcoding"),
    ("network", "network"),
    ("metadata", "metadata"),
    ("branding", "general"),
)

_SENSITIVE = re.compile(
    r"(token|password|passwd|secret|api_?key|privatekey|certificatekey|identifier|uuid|mail|"
    r"onlineusername|certificatepassword)",
    re.IGNORECASE,
)
_KEYWORD_CATEGORIES = (
    (re.compile(r"subtitle", re.I), "subtitles"),
    (re.compile(r"(publish|remoteaccess|manualport|mappedport|relay|upnp|publicport|publichttps|"
                r"enableremoteaccess|remoteip)", re.I), "remote_access"),
    (re.compile(r"(secureconnection|allowednetworks|lockout|loginattempt|quickconnect|"
                r"cors|requirehttps|knownproxies|certificate|ipaddressfilter|remoteipfilter)", re.I), "security"),
    (re.compile(r"(^wan|bandwidth|bitrate|streaming|maxstreams|throttl|resume|playback)", re.I), "streaming"),
    (re.compile(r"(butler|scheduled|task)", re.I), "scheduled_tasks"),
)
_PLEX_GROUPS = {
    "general": "general",
    "network": "network",
    "transcoder": "transcoding",
    "library": "libraries",
    "extras": "libraries",
    "butler": "scheduled_tasks",
    "scheduled": "scheduled_tasks",
    "agents": "metadata",
    "dlna": "advanced",
    "channels": "advanced",
}


class ServerConfigurationError(RuntimeError):
    """A read that could not complete; the message is a translation key."""


def is_sensitive(key: str) -> bool:
    return bool(_SENSITIVE.search(str(key or "")))


def _keyword_category(key: str, fallback: str) -> str:
    for pattern, category in _KEYWORD_CATEGORIES:
        if pattern.search(key):
            return category
    return fallback


def humanize_key(key: str) -> str:
    """`EnableHardwareEncoding` -> `Enable hardware encoding`."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|_", " ", str(key or "")).split()
    if not words:
        return str(key or "")
    text = " ".join(word if word.isupper() and len(word) > 1 else word.lower() for word in words)
    return text[:1].upper() + text[1:]


def _display(value):
    """Scalar values stay as they are; lists and objects become a short summary."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value, True
    if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
        return ", ".join("" if item is None else str(item) for item in value), False
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:500], False
    return str(value), False


def _setting(*, key, source, category, value, label=None, summary="", default=None, value_type=None,
             choices=None, writable=True, advanced=False):
    sensitive = is_sensitive(key)
    value, scalar = _display(value)
    default, _ = _display(default)
    if value_type is None:
        value_type = ("bool" if isinstance(value, bool) else "int" if isinstance(value, int)
                      else "double" if isinstance(value, float) else "text" if scalar else "list")
    item = {
        "key": key,
        "source": source,
        "category": category if category in CATEGORIES else "advanced",
        "label": label or humanize_key(key.rsplit(".", 1)[-1]),
        "summary": summary or "",
        "value": MASK if sensitive and value not in (None, "") else value,
        "default": None if sensitive else default,
        "type": value_type,
        "choices": [] if sensitive else (choices or []),
        "writable": bool(writable and scalar and not sensitive),
        "advanced": bool(advanced or not scalar),
        "sensitive": sensitive,
    }
    item["modified"] = (not sensitive and default is not None and str(value) != str(default))
    item["compare_key"] = key
    return item


def library_compare_key(library_name, key):
    """Library settings are compared across servers by library name, not by id."""
    name = " ".join(str(library_name or "").lower().split())
    return f"library[{name}].{str(key).rsplit('.', 1)[-1]}"


def _result(server, settings, errors):
    by_category = {}
    for item in settings:
        by_category.setdefault(item["category"], []).append(item)
    return {
        "server_id": server["id"],
        "provider": server["type"],
        "settings": settings,
        "categories": [category for category in CATEGORIES if by_category.get(category)],
        "counts": {category: len(by_category.get(category, [])) for category in CATEGORIES},
        "errors": errors,
        "read_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Plex
# ---------------------------------------------------------------------------

def _plex_choices(raw) -> list:
    choices = []
    for part in str(raw or "").split("|"):
        if not part:
            continue
        value, _, label = part.partition(":")
        choices.append({"value": value, "label": label or value})
    return choices


def _plex_category(setting: dict) -> str:
    if setting.get("hidden"):
        return "advanced"
    group = str(setting.get("group") or "").strip().lower()
    return _keyword_category(str(setting.get("id") or ""), _PLEX_GROUPS.get(group, "advanced"))


def _plex_settings(rows, *, source="server", key_prefix=""):
    settings = []
    for row in rows or []:
        key = str(row.get("id") or "").strip()
        if not key:
            continue
        settings.append(_setting(
            key=key_prefix + key,
            source=source,
            category="libraries" if source == "library" else _plex_category(row),
            value=row.get("value"),
            label=row.get("label") or None,
            summary=row.get("summary") or "",
            default=row.get("default"),
            value_type=row.get("type") or None,
            choices=_plex_choices(row.get("enumValues")),
            advanced=bool(row.get("advanced") or row.get("hidden")),
        ))
    return settings


class _Reader:
    def __init__(self, server, deadline, priority=True):
        self.server = server
        self.deadline = deadline
        self.priority = priority
        self.http = server_http_session(server)
        self.bases = candidate_bases(server)
        self.base = None

    def remaining(self):
        return self.deadline - time.monotonic()

    def get_json(self, path, headers, *, plex=False):
        bases = [self.base] if self.base else self.bases
        last_status = None
        for base in bases:
            if self.remaining() <= 0:
                raise ServerConfigurationError("server_config_read_timeout")
            if plex:
                try:
                    wait_for_plex_slot(base, priority=self.priority, deadline=self.deadline)
                except TimeoutError:
                    raise ServerConfigurationError("server_config_read_timeout") from None
            try:
                response = self.http.get(base + path, headers=headers, allow_redirects=False,
                                         timeout=max(1, min(REQUEST_TIMEOUT_SECONDS, self.remaining())))
            except Exception as exc:
                logger.warning("Server configuration read failed: server_id=%s path=%s error=%s",
                               self.server.get("id"), path.split("?", 1)[0], type(exc).__name__)
                continue
            last_status = response.status_code
            if response.status_code in (401, 403):
                raise ServerConfigurationError("server_config_not_admin")
            if response.status_code != 200:
                continue
            self.base = base
            try:
                return response.json()
            except ValueError:
                raise ServerConfigurationError("server_config_unexpected_answer") from None
        if last_status is None:
            raise ServerConfigurationError("server_config_unreachable")
        raise ServerConfigurationError("server_config_unexpected_answer")

    def close(self):
        self.http.close()


def read_plex_configuration(server, libraries=(), *, budget_seconds=READ_BUDGET_SECONDS, priority=True):
    """Plex preferences and library options.

    priority=True is for a page the admin is waiting on; background checks pass
    False so they queue behind posters and Now Playing.
    """
    token = str(server.get("token") or "").strip()
    if not token:
        raise ServerConfigurationError("server_config_missing_token")
    reader = _Reader(server, time.monotonic() + budget_seconds, priority=priority)
    headers = {"X-Plex-Token": token, "Accept": "application/json"}
    errors = []
    try:
        container = (reader.get_json("/:/prefs", headers, plex=True) or {}).get("MediaContainer") or {}
        settings = _plex_settings(container.get("Setting"))
        for library in libraries or ():
            section = str(library.get("section_id") or "").strip()
            if not section.isdigit():
                continue
            try:
                data = reader.get_json(f"/library/sections/{section}/prefs", headers, plex=True)
            except ServerConfigurationError as exc:
                errors.append({"library": library.get("name") or section, "error": str(exc)})
                if str(exc) in ("server_config_read_timeout", "server_config_unreachable"):
                    break
                continue
            rows = ((data or {}).get("MediaContainer") or {}).get("Setting")
            name = library.get("name") or section
            for item in _plex_settings(rows, source="library", key_prefix=f"library.{section}."):
                item["library"] = name
                item["compare_key"] = library_compare_key(name, item["key"])
                settings.append(item)
    finally:
        reader.close()
    return _result(server, settings, errors)


# ---------------------------------------------------------------------------
# Jellyfin
# ---------------------------------------------------------------------------

def _jellyfin_object_settings(data, *, source, fallback, key_prefix="", library=None):
    settings = []
    for key, value in sorted((data or {}).items()):
        full_key = key_prefix + key
        category = _keyword_category(key, fallback)
        if fallback == "libraries":
            category = "subtitles" if "subtitle" in key.lower() else "libraries"
        item = _setting(key=full_key, source=source, category=category, value=value,
                        label=humanize_key(key))
        if library:
            item["library"] = library
            item["compare_key"] = library_compare_key(library, full_key)
        settings.append(item)
    return settings


def _jellyfin_general_category(key: str) -> str:
    lowered = key.lower()
    if any(word in lowered for word in ("metadata", "image", "fetcher", "chapter", "trickplay")):
        return "metadata"
    if any(word in lowered for word in ("library", "scan", "folder", "watcher", "sort", "monitor")):
        return "libraries"
    if any(word in lowered for word in ("log", "cache", "path", "plugin", "activitylog")):
        return "advanced"
    return _keyword_category(key, "general")


JELLYFIN_SECTIONS = ("encoding", "network", "metadata", "branding", "libraries", "scheduled_tasks")


def read_jellyfin_configuration(server, *, budget_seconds=READ_BUDGET_SECONDS, sections=None):
    """Jellyfin configuration. sections limits the optional reads (None reads all)."""
    wanted = set(JELLYFIN_SECTIONS if sections is None else sections)
    token = str(server.get("token") or "").strip()
    if not token:
        raise ServerConfigurationError("server_config_missing_token")
    reader = _Reader(server, time.monotonic() + budget_seconds)
    headers = {**jellyfin_headers(token), "Accept": "application/json"}
    errors = []
    settings = []
    try:
        general = reader.get_json("/System/Configuration", headers) or {}
        for key, value in sorted(general.items()):
            settings.append(_setting(key=key, source="system", category=_jellyfin_general_category(key),
                                     value=value, label=humanize_key(key)))
        for name, category in JELLYFIN_NAMED_CONFIGURATIONS:
            if name not in wanted:
                continue
            try:
                data = reader.get_json(f"/System/Configuration/{name}", headers) or {}
            except ServerConfigurationError as exc:
                errors.append({"section": name, "error": str(exc)})
                continue
            settings.extend(_jellyfin_object_settings(data, source=name, fallback=category,
                                                      key_prefix=f"{name}."))
        folders = []
        if "libraries" in wanted:
            try:
                folders = reader.get_json("/Library/VirtualFolders", headers) or []
            except ServerConfigurationError as exc:
                errors.append({"section": "libraries", "error": str(exc)})
        for folder in folders:
            name = folder.get("Name") or folder.get("ItemId") or "?"
            options = dict(folder.get("LibraryOptions") or {})
            options.pop("PathInfos", None)  # Local paths stay on the server.
            settings.extend(_jellyfin_object_settings(
                options, source="library", fallback="libraries",
                key_prefix=f"library.{folder.get('ItemId') or name}.", library=name))
        tasks = []
        if "scheduled_tasks" in wanted:
            try:
                tasks = reader.get_json("/ScheduledTasks?isHidden=false", headers) or []
            except ServerConfigurationError as exc:
                errors.append({"section": "scheduled_tasks", "error": str(exc)})
        for task in tasks:
            triggers = [
                {key: trigger.get(key) for key in ("Type", "TimeOfDayTicks", "IntervalTicks", "DayOfWeek")
                 if trigger.get(key) is not None}
                for trigger in task.get("Triggers") or []
            ]
            item = _setting(key=f"task.{task.get('Key') or task.get('Id')}", source="scheduled_task",
                            category="scheduled_tasks", value=triggers or [],
                            label=task.get("Name") or humanize_key(str(task.get("Key") or "")),
                            summary=task.get("Description") or "")
            item["value"] = describe_jellyfin_triggers(triggers)
            settings.append(item)
    finally:
        reader.close()
    return _result(server, settings, errors)


def describe_jellyfin_triggers(triggers) -> str:
    """Short, language-neutral summary of Jellyfin task triggers."""
    parts = []
    for trigger in triggers or []:
        kind = str(trigger.get("Type") or "")
        if kind == "IntervalTrigger" and trigger.get("IntervalTicks"):
            hours = int(trigger["IntervalTicks"]) / 36_000_000_000
            parts.append(f"every {hours:g} h")
        elif kind in ("DailyTrigger", "WeeklyTrigger") and trigger.get("TimeOfDayTicks") is not None:
            seconds = int(trigger["TimeOfDayTicks"]) // 10_000_000
            at = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
            day = f"{trigger.get('DayOfWeek')} " if kind == "WeeklyTrigger" else "daily "
            parts.append(f"{day}{at}")
        elif kind:
            parts.append(kind.replace("Trigger", "").lower())
    return ", ".join(parts) or "—"


def load_media_server(db, server_id):
    """Return (server, libraries) for a Plex/Jellyfin server; raises ServerConfigurationError."""
    row = db.query_one(
        """SELECT id, name, LOWER(TRIM(type)) AS type, url, local_url, public_url, token, settings_json
           FROM servers WHERE id=? AND LOWER(TRIM(type)) IN ('plex','jellyfin')""",
        (int(server_id),),
    )
    if not row:
        raise ServerConfigurationError("server_config_unknown_server")
    server = dict(row)
    libraries = []
    if server["type"] == "plex":
        libraries = [dict(item) for item in db.query(
            "SELECT section_id, name FROM libraries WHERE server_id=? ORDER BY name COLLATE NOCASE",
            (server["id"],)) or []]
    return server, libraries


def read_loaded_server(server, libraries=(), *, priority=True, sections=None, budget_seconds=READ_BUDGET_SECONDS):
    """Network part of a read; safe to run in a worker thread (no database access)."""
    if not candidate_bases(server):
        raise ServerConfigurationError("server_config_missing_url")
    if server["type"] == "plex":
        return read_plex_configuration(server, libraries, budget_seconds=budget_seconds, priority=priority)
    return read_jellyfin_configuration(server, budget_seconds=budget_seconds, sections=sections)


def read_server_configuration(db, server_id):
    """Read one Plex or Jellyfin server; raises ServerConfigurationError."""
    server, libraries = load_media_server(db, server_id)
    return read_loaded_server(server, libraries)
