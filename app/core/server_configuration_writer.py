"""Configuration Manager step 4: write settings to Plex and Jellyfin.

This is the only module of the Configuration Manager that changes a server.
It is called for one server at a time, after the administrator confirmed a
previewed deployment. Each write uses the server's configured connection, a
bounded time budget, and only the settings it was given:

- Plex: PUT /:/prefs?key=value for server settings and
  PUT /library/sections/{id}/prefs?key=value for library options.
- Jellyfin: the current configuration object is read, only the given keys
  are changed (keeping their JSON type), and the whole object is posted back:
  /System/Configuration, /System/Configuration/{name} and
  /Library/VirtualFolders/LibraryOptions (library paths are sent back as read).

Values are verified afterwards by reading the server again (see
server_configuration_deploy), never assumed.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from core.http_security import server_http_session
from core.jellyfin_auth import jellyfin_headers
from core.monitoring.resource_stats import candidate_bases
from core.plex_rate_limit import wait_for_plex_slot
from logging_utils import get_logger

logger = get_logger("server_configuration")

WRITE_BUDGET_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 15
JELLYFIN_NAMED = ("encoding", "network", "metadata", "branding")


class WriteError(Exception):
    """A write that failed; the message is a translation key."""


def split_key(compare_key: str):
    """('library', name, setting) | ('section', name, setting) | ('server', None, setting)."""
    if compare_key.startswith("library[") and "]." in compare_key:
        end = compare_key.index("].")
        return "library", compare_key[len("library["):end], compare_key[end + 2:]
    head, _, tail = compare_key.partition(".")
    if tail and head in JELLYFIN_NAMED:
        return "section", head, tail
    return "server", None, compare_key


def _normal_name(name) -> str:
    return " ".join(str(name or "").lower().split())


def convert_like(current, value: str):
    """Convert a profile value (normalized text) to the JSON type of the current value."""
    if isinstance(current, bool):
        if value not in ("true", "false"):
            raise WriteError("config_deploy_bad_value")
        return value == "true"
    if isinstance(current, int):
        try:
            return int(value)
        except ValueError:
            raise WriteError("config_deploy_bad_value") from None
    if isinstance(current, float):
        try:
            return float(value)
        except ValueError:
            raise WriteError("config_deploy_bad_value") from None
    if isinstance(current, (list, dict)):
        raise WriteError("config_deploy_unsupported")
    return value


class _Writer:
    def __init__(self, server, budget_seconds):
        self.server = server
        self.deadline = time.monotonic() + budget_seconds
        self.http = server_http_session(server)
        self.bases = candidate_bases(server)
        self.base = None

    def remaining(self):
        return self.deadline - time.monotonic()

    def call(self, method, path, *, headers, plex=False, json_body=None):
        bases = [self.base] if self.base else self.bases
        if not bases:
            raise WriteError("server_config_missing_url")
        last_status = None
        for base in bases:
            if self.remaining() <= 0:
                raise WriteError("server_config_read_timeout")
            if plex:
                try:
                    wait_for_plex_slot(base, priority=True, deadline=self.deadline)
                except TimeoutError:
                    raise WriteError("server_config_read_timeout") from None
            try:
                response = self.http.request(method, base + path, headers=headers, json=json_body,
                                             allow_redirects=False,
                                             timeout=max(1, min(REQUEST_TIMEOUT_SECONDS, self.remaining())))
            except Exception as exc:
                logger.warning("Server configuration write failed: server_id=%s method=%s path=%s error=%s",
                               self.server.get("id"), method, path.split("?", 1)[0], type(exc).__name__)
                continue
            last_status = response.status_code
            if response.status_code in (401, 403):
                raise WriteError("server_config_not_admin")
            if response.status_code >= 400:
                continue
            self.base = base
            return response
        if last_status is None:
            raise WriteError("server_config_unreachable")
        raise WriteError("config_deploy_refused")

    def get_json(self, path, headers):
        response = self.call("GET", path, headers=headers)
        try:
            return response.json()
        except ValueError:
            raise WriteError("server_config_unexpected_answer") from None

    def close(self):
        self.http.close()


def apply_plex(server, changes, libraries=(), *, budget_seconds=WRITE_BUDGET_SECONDS) -> dict:
    """changes: {compare_key: value}. Returns {compare_key: None (sent) | error key}."""
    token = str(server.get("token") or "").strip()
    if not token:
        return {key: "server_config_missing_token" for key in changes}
    sections = {_normal_name(lib.get("name")): str(lib.get("section_id") or "") for lib in libraries or ()}
    batches = {}  # path -> {setting: value}
    results = {}
    for key, value in changes.items():
        kind, name, setting = split_key(key)
        if kind == "library":
            section = sections.get(name, "")
            if not section.isdigit():
                results[key] = "config_deploy_missing_library"
                continue
            path = f"/library/sections/{section}/prefs"
        elif kind == "server":
            path = "/:/prefs"
        else:
            results[key] = "config_deploy_unsupported"
            continue
        batches.setdefault(path, {})[key] = (setting, value)
    writer = _Writer(server, budget_seconds)
    headers = {"X-Plex-Token": token, "Accept": "application/json"}
    try:
        for path, entries in batches.items():
            query = urlencode({setting: value for setting, value in entries.values()})
            try:
                writer.call("PUT", f"{path}?{query}", headers=headers, plex=True)
                outcome = None
            except WriteError as exc:
                outcome = str(exc)
            for key in entries:
                results[key] = outcome
    finally:
        writer.close()
    return results


def apply_jellyfin(server, changes, *, budget_seconds=WRITE_BUDGET_SECONDS) -> dict:
    """changes: {compare_key: value}. Returns {compare_key: None (sent) | error key}."""
    token = str(server.get("token") or "").strip()
    if not token:
        return {key: "server_config_missing_token" for key in changes}
    headers = {**jellyfin_headers(token), "Accept": "application/json"}
    groups = {}
    for key, value in changes.items():
        kind, name, setting = split_key(key)
        groups.setdefault((kind, name), {})[key] = (setting, value)
    results = {}
    writer = _Writer(server, budget_seconds)
    try:
        folders = None
        for (kind, name), entries in groups.items():
            try:
                if kind == "library":
                    if folders is None:
                        folders = writer.get_json("/Library/VirtualFolders", headers) or []
                    folder = next((f for f in folders if _normal_name(f.get("Name")) == name), None)
                    if not folder or not folder.get("ItemId"):
                        raise WriteError("config_deploy_missing_library")
                    options = dict(folder.get("LibraryOptions") or {})
                    _apply_entries(options, entries, results)
                    if any(results.get(key) is None for key in entries):
                        writer.call("POST", "/Library/VirtualFolders/LibraryOptions", headers=headers,
                                    json_body={"Id": folder["ItemId"], "LibraryOptions": options})
                else:
                    path = "/System/Configuration" + (f"/{name}" if kind == "section" else "")
                    data = writer.get_json(path, headers)
                    if not isinstance(data, dict):
                        raise WriteError("server_config_unexpected_answer")
                    _apply_entries(data, entries, results)
                    if any(results.get(key) is None for key in entries):
                        writer.call("POST", path, headers=headers, json_body=data)
            except WriteError as exc:
                for key in entries:
                    if results.get(key) is None:
                        results[key] = str(exc)
    finally:
        writer.close()
    return results


def _apply_entries(data, entries, results):
    for key, (setting, value) in entries.items():
        if setting not in data:
            results[key] = "config_deploy_missing_setting"
            continue
        try:
            data[setting] = convert_like(data[setting], value)
            results[key] = None
        except WriteError as exc:
            results[key] = str(exc)


def apply_changes(server, changes, libraries=()) -> dict:
    if server.get("type") == "plex":
        return apply_plex(server, changes, libraries)
    if server.get("type") == "jellyfin":
        return apply_jellyfin(server, changes)
    return {key: "server_config_unknown_server" for key in changes}
