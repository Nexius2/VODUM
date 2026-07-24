from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from logging_utils import get_logger, is_debug_mode_enabled


log = get_logger("plex_sync_api")


def fetch_xml(url: str, token: str) -> Optional[ET.Element]:
    from core.http_security import ConfiguredHostSession, url_origin

    headers = {
        "X-Plex-Token": token,
        "Accept": "application/xml",
        "X-Plex-Client-Identifier": "vodum-sync-plex",
    }
    if is_debug_mode_enabled():
        log.debug("[API] GET %s", url)
    try:
        session = ConfiguredHostSession(
            {url_origin("https://plex.tv")},
            default_timeout=20,
        )
        response = session.get(url, headers=headers)
    except Exception as exc:
        log.error("[API] Network error on %s: %s", url, exc)
        return None
    if response.status_code != 200:
        log.error(
            "[API] %s -> HTTP %s: %s",
            url,
            response.status_code,
            response.text[:200],
        )
        return None
    try:
        return ET.fromstring(response.content)
    except Exception as exc:
        log.error("[API] Invalid XML for %s: %s", url, exc)
        return None


def fetch_admin_account_from_token(token: str) -> Optional[Dict[str, Any]]:
    root = fetch_xml("https://plex.tv/users/account", token)
    if root is None:
        log.error("[API] Unable to retrieve /users/account")
        return None
    plex_id = root.get("id")
    if not plex_id:
        log.error("[API] /users/account does not contain an ID")
        return None
    return {
        "plex_id": str(plex_id),
        "username": root.get("username") or root.get("title") or f"user_{plex_id}",
        "email": (root.get("email") or "").strip() or None,
        "avatar": root.get("thumb") or root.get("avatar"),
        "plex_role": "owner",
        "home": 0,
        "protected": 0,
        "restricted": 0,
        "allow_sync": 1,
        "allow_camera_upload": 1,
        "allow_channels": 1,
        "filter_all": None,
        "filter_movies": None,
        "filter_television": None,
        "filter_music": None,
        "filter_photos": None,
        "recommendations_playlist_id": None,
        "joined_at": None,
        "accepted_at": None,
        "subscription_active": None,
        "subscription_status": None,
        "subscription_plan": None,
        "servers": [],
    }


def fetch_users_from_plex_api(token: str, db=None) -> Dict[str, Dict[str, Any]]:
    root = fetch_xml("https://plex.tv/api/users", token)
    if root is None:
        log.error("[API] Unable to retrieve /api/users -> Aborted.")
        return {}
    users = {}
    for node in root.findall("User"):
        plex_id = node.get("id")
        if not plex_id:
            continue
        plex_id = str(plex_id)
        home = int(node.get("home") == "1")
        subscription = node.find("subscription")
        servers = [
            {
                "machineIdentifier": server.get("machineIdentifier"),
                "name": server.get("name"),
                "home": int(server.get("home") == "1"),
                "owned": int(server.get("owned") == "1"),
                "allLibraries": int(server.get("allLibraries") == "1"),
                "numLibraries": int(server.get("numLibraries") or 0),
                "lastSeenAt": server.get("lastSeenAt"),
                "pending": int(server.get("pending") == "1"),
            }
            for server in node.findall("Server")
        ]
        users[plex_id] = {
            "plex_id": plex_id,
            "username": node.get("username") or node.get("title") or f"user_{plex_id}",
            "email": (node.get("email") or "").strip(),
            "avatar": node.get("thumb"),
            "plex_role": "home" if home else "friend",
            "home": home,
            "protected": int(node.get("protected") == "1"),
            "restricted": int(node.get("restricted") == "1"),
            "allow_sync": int(node.get("allowSync") == "1"),
            "allow_camera_upload": int(node.get("allowCameraUpload") == "1"),
            "allow_channels": int(node.get("allowChannels") == "1"),
            "filter_all": node.get("filterAll"),
            "filter_movies": node.get("filterMovies"),
            "filter_television": node.get("filterTelevision"),
            "filter_music": node.get("filterMusic"),
            "filter_photos": node.get("filterPhotos"),
            "recommendations_playlist_id": node.get("recommendationsPlaylistId"),
            "joined_at": node.get("joinedAt"),
            "accepted_at": node.get("acceptedAt"),
            "subscription_active": subscription.get("active") if subscription is not None else None,
            "subscription_status": subscription.get("status") if subscription is not None else None,
            "subscription_plan": subscription.get("plan") if subscription is not None else None,
            "servers": servers,
        }
    log.info("[API] /api/users -> %s User(s) retrieved.", len(users))
    return users


def fetch_shared_server_users(
    token: str,
    machine_identifier: str,
    db=None,
) -> Dict[str, Dict[str, Any]]:
    from core.http_security import ConfiguredHostSession, url_origin

    if not token or not machine_identifier:
        return {}
    session = ConfiguredHostSession(
        {url_origin("https://plex.tv")},
        default_timeout=20,
    )
    url = f"https://plex.tv/api/servers/{machine_identifier}/shared_servers"
    response = None
    try:
        response = session.get(url, headers={"X-Plex-Token": token})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        result = {}
        for shared in root.findall("SharedServer"):
            plex_id = str(
                shared.get("userID")
                or shared.get("userId")
                or shared.get("id")
                or ""
            ).strip()
            if not plex_id:
                continue
            truthy = lambda value: str(value or "0").lower() in {"1", "true"}
            result[plex_id] = {
                "plex_id": plex_id,
                "username": shared.get("username") or shared.get("title") or shared.get("name") or f"plex_{plex_id}",
                "email": shared.get("email") or None,
                "avatar": shared.get("thumb") or shared.get("avatar") or "",
                "plex_role": "friend",
                "home": truthy(shared.get("home")),
                "protected": False,
                "restricted": truthy(shared.get("restricted")),
                "allow_sync": truthy(shared.get("allowSync")),
                "allow_camera_upload": False,
                "allow_channels": False,
                "joined_at": shared.get("invitedAt"),
                "accepted_at": shared.get("acceptedAt"),
                "servers": [{"machineIdentifier": machine_identifier}],
            }
        return result
    except Exception as exc:
        preview = ""
        try:
            preview = response.text[:500] if response is not None else ""
        except Exception:
            pass
        log.error(
            "[SYNC USERS] shared_servers failed | machine_identifier=%s | "
            "url=%s | error=%s | response_preview=%s",
            machine_identifier,
            url,
            exc,
            preview,
        )
        return {}
