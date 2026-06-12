"""Provider-neutral media-server validation used by setup and configuration flows."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from core.http_security import plex_server_http_session
from tasks.check_servers import jellyfin_get_status


def _validate_plex_token_on_plextv(token: str) -> tuple[bool, str | None]:
    try:
        response = requests.get(
            "https://plex.tv/users/account",
            headers={
                "X-Plex-Token": token,
                "Accept": "application/xml",
            },
            timeout=10,
        )

        if response.status_code in (401, 422):
            return False, "This Plex token is valid locally but rejected by plex.tv. Use the Plex owner account token."

        if response.status_code != 200:
            return False, f"plex.tv returned HTTP {response.status_code} while checking the token."

        account = ET.fromstring(response.content)
        username = account.get("username") or account.get("title") or account.get("email")

        return True, username

    except Exception as exc:
        return False, f"Unable to validate the token on plex.tv: {exc}"


def _validate_plex(server: dict, base_url: str, token: str) -> tuple:
    try:
        response = plex_server_http_session(server).get(
            f"{base_url}/identity",
            headers={"X-Plex-Token": token, "Accept": "application/xml"},
            timeout=10,
        )

        if response.status_code == 401:
            return ("down", None, None, "Plex rejected the token locally (HTTP 401).")

        if response.status_code != 200:
            return ("down", None, None, f"Plex returned HTTP {response.status_code}.")

        plex_tv_ok, plex_tv_message = _validate_plex_token_on_plextv(token)
        if not plex_tv_ok:
            return ("down", None, None, plex_tv_message)

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