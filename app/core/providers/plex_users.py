from typing import Any, Dict, List, Optional

from logging_utils import get_logger

log = get_logger("plex_users")


def _pick_base_url(server_row: Dict[str, Any]) -> str:
    base = ((server_row.get("url") or "") or (server_row.get("local_url") or "")).strip().rstrip("/")
    if not base:
        raise RuntimeError("Plex: missing server URL (url/local_url)")
    return base


def _token(server_row: Dict[str, Any]) -> str:
    token = (server_row.get("token") or "").strip()
    if not token:
        raise RuntimeError("Plex: missing token (servers.token)")
    return token


def plex_invite_and_share(
    server_row: Dict[str, Any],
    *,
    email: str,
    libraries_names: List[str],
    allow_sync: bool = False,
    allow_camera_upload: bool = False,
    allow_channels: bool = False,
    filter_movies: str = "",
    filter_television: str = "",
    filter_music: str = "",
) -> Dict[str, Any]:
    """
    Invite a Plex account (by email) and share selected libraries.

    Notes:
      - Plex does not create local users. It invites a Plex account.
      - Depending on user state, Plex may not immediately expose a stable external id.
      - We return best-effort info: {"invited": True, "external_user_id": str|None, "username": str|None}
    """
    email = (email or "").strip()
    if not email:
        raise ValueError("Plex invite: email is required")

    try:
        from plexapi.server import PlexServer
    except Exception as e:
        raise RuntimeError(f"plexapi not available: {e}")

    base = _pick_base_url(server_row)
    token = _token(server_row)

    plex = PlexServer(base, token)
    account = plex.myPlexAccount()

    sections = [str(x).strip() for x in (libraries_names or []) if str(x).strip()]

    invited = False
    invited_username = None
    external_user_id = None

    # 1) inviteFriend (if not already friend)
    try:
        account.inviteFriend(
            user=email,
            server=plex,
            sections=sections,
        )
        invited = True
        log.info(f"Plex inviteFriend OK: email={email} server={plex.friendlyName} sections={sections}")
    except Exception as e:
        log.warning(f"Plex inviteFriend failed/ignored: email={email} err={e}")

    # 2) updateFriend (if already friend OR to ensure libs)
    try:
        plex_user = account.user(email)
        invited_username = getattr(plex_user, "username", None) or getattr(plex_user, "title", None)
        external_user_id = getattr(plex_user, "id", None)

        account.updateFriend(
            user=plex_user,
            server=plex,
            sections=sections,
        )
        log.info(f"Plex updateFriend OK: user={invited_username or email} server={plex.friendlyName}")
    except Exception as e:
        log.warning(f"Plex updateFriend (libs) failed (may be pending invite): email={email} err={e}")

    return {
        "invited": invited,
        "username": invited_username,
        "external_user_id": str(external_user_id) if external_user_id else None,
    }
