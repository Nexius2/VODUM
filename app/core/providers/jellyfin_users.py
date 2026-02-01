import json
from typing import Any, Dict, List, Optional

import requests

from logging_utils import get_logger

log = get_logger("jellyfin_users")


def _pick_base_url(server_row: Dict[str, Any]) -> str:
    """Prefer public_url, else url, else local_url."""
    base = (
        (server_row.get("public_url") or "")
        or (server_row.get("url") or "")
        or (server_row.get("local_url") or "")
    ).strip().rstrip("/")
    if not base:
        raise RuntimeError("Jellyfin: missing server URL (public_url/url/local_url)")
    return base


def _api_key(server_row: Dict[str, Any]) -> str:
    token = (server_row.get("token") or "").strip()
    if not token:
        raise RuntimeError("Jellyfin: missing token (servers.token)")
    return token


def _headers() -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def jellyfin_list_users(server_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    base = _pick_base_url(server_row)
    api_key = _api_key(server_row)
    r = requests.get(f"{base}/Users", params={"api_key": api_key}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def jellyfin_create_user(
    server_row: Dict[str, Any],
    username: str,
) -> Dict[str, Any]:
    """Create a local Jellyfin user and return the created user object."""
    if not username or not str(username).strip():
        raise ValueError("Jellyfin: username is required")

    base = _pick_base_url(server_row)
    api_key = _api_key(server_row)

    payload = {"Name": username.strip()}
    r = requests.post(
        f"{base}/Users/New",
        params={"api_key": api_key},
        json=payload,
        headers=_headers(),
        timeout=20,
    )

    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:
            err = r.text
        raise RuntimeError(f"Jellyfin: create user failed ({r.status_code}) {err}")

    user = r.json() if r.content else {}
    if not isinstance(user, dict) or not user.get("Id"):
        for u in jellyfin_list_users(server_row):
            if (u.get("Name") or "").strip().lower() == username.strip().lower():
                return u
        raise RuntimeError("Jellyfin: create user did not return an Id")

    return user


def jellyfin_set_password(
    server_row: Dict[str, Any],
    jellyfin_user_id: str,
    password: str,
) -> None:
    """Set the password for a Jellyfin user."""
    if not password:
        return

    base = _pick_base_url(server_row)
    api_key = _api_key(server_row)

    payload = {
        "CurrentPassword": "",
        "NewPassword": password,
    }

    r = requests.post(
        f"{base}/Users/{jellyfin_user_id}/Password",
        params={"api_key": api_key},
        json=payload,
        headers=_headers(),
        timeout=20,
    )

    if r.status_code >= 400:
        raise RuntimeError(
            f"Jellyfin: set password failed ({r.status_code}) {r.text}"
        )


def jellyfin_set_policy_folders(
    server_row: Dict[str, Any],
    jellyfin_user_id: str,
    enabled_folders: List[str],
    *,
    force_password_change: bool = False,
) -> None:
    """Apply a minimal policy: restrict EnabledFolders."""
    base = _pick_base_url(server_row)
    api_key = _api_key(server_row)

    r = requests.get(
        f"{base}/Users/{jellyfin_user_id}",
        params={"api_key": api_key},
        timeout=20,
    )
    r.raise_for_status()
    user_obj = r.json() if r.content else {}
    policy = user_obj.get("Policy") or {}
    if not isinstance(policy, dict):
        policy = {}

    policy["EnableAllFolders"] = False
    policy["EnabledFolders"] = [str(x) for x in (enabled_folders or [])]

    url = f"{base}/Users/{jellyfin_user_id}/Policy"
    r2 = requests.post(
        url,
        params={"api_key": api_key},
        json=policy,
        headers=_headers(),
        timeout=20,
    )
    if r2.status_code in (405, 415):
        r2 = requests.put(
            url,
            params={"api_key": api_key},
            json=policy,
            headers=_headers(),
            timeout=20,
        )
    r2.raise_for_status()


def jellyfin_reset_password_required(
    server_row: Dict[str, Any],
    jellyfin_user_id: str,
    required: bool,
) -> None:
    """Best-effort: mark user as needing password reset if supported by the server."""
    try:
        base = _pick_base_url(server_row)
        api_key = _api_key(server_row)
        r = requests.get(
            f"{base}/Users/{jellyfin_user_id}",
            params={"api_key": api_key},
            timeout=20,
        )
        r.raise_for_status()
        user_obj = r.json() if r.content else {}
        policy = user_obj.get("Policy") or {}
        if not isinstance(policy, dict):
            policy = {}

        policy["RequirePasswordChange"] = bool(required)

        url = f"{base}/Users/{jellyfin_user_id}/Policy"
        r2 = requests.post(
            url,
            params={"api_key": api_key},
            json=policy,
            headers=_headers(),
            timeout=20,
        )
        if r2.status_code in (405, 415):
            r2 = requests.put(
                url,
                params={"api_key": api_key},
                json=policy,
                headers=_headers(),
                timeout=20,
            )
        r2.raise_for_status()
    except Exception as e:
        log.warning(f"Jellyfin: cannot set RequirePasswordChange (ignored): {e}")
