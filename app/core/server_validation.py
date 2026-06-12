"""Provider-neutral media-server validation used by setup and configuration flows."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from core.http_security import plex_server_http_session
from tasks.check_servers import jellyfin_get_status


def _validate_plex(server: dict, base_url: str, token: str) -> tuple:
    try:
        response = plex_server_http_session(server).get(
            f"{base_url}/identity",
            headers={"X-Plex-Token": token, "Accept": "application/xml"},
            timeout=10,
        )
        if response.status_code == 401:
            return ("down", None, None, "Plex rejected the token (HTTP 401).")
        if response.status_code != 200:
            return ("down", None, None, f"Plex returned HTTP {response.status_code}.")

        identity = ET.fromstring(response.content)
        root = plex_server_http_session(server).get(
            f"{base_url}/",
            headers={"X-Plex-Token": token, "Accept": "application/xml"},
            timeout=10,
        )
        friendly_name = ET.fromstring(root.content).get("friendlyName") if root.status_code == 200 else None
        return (
            "up",
            friendly_name or "Plex",
            identity.get("machineIdentifier"),
            identity.get("version"),
        )
    except Exception as exc:
        return ("down", None, None, f"Plex connection failed: {exc}")


def validate_media_server(server_type: str, base_url: str, token: str, *, server: dict | None = None) -> tuple:
    provider = str(server_type or "").strip().lower()
    candidate = dict(server or {})
    candidate.setdefault("url", base_url)
    candidate.setdefault("local_url", None)
    candidate.setdefault("public_url", None)
    candidate.setdefault("settings_json", '{"verify_tls": true}')
    if provider == "plex":
        return _validate_plex(candidate, base_url, token)
    if provider == "jellyfin":
        return jellyfin_get_status(candidate, base_url, token)
    return ("down", None, None, f"Unsupported provider: {provider or 'unknown'}")
