from typing import Any, Dict, List

from logging_utils import get_logger

log = get_logger("plex_users")


def _pick_base_url(server_row: Dict[str, Any]) -> str:
    def _clean(value: Any) -> str:
        v = str(value or "").strip()
        if v.lower() in ("", "none", "null"):
            return ""
        return v.rstrip("/")

    base = (
        _clean(server_row.get("url"))
        or _clean(server_row.get("local_url"))
        or _clean(server_row.get("public_url"))
    )

    if not base:
        raise RuntimeError("Plex: missing server URL (url/local_url/public_url)")

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
    """Invite a Plex account (by email) and share selected libraries.

    - If already friend => updateFriend only.
    - If not friend:
        - if invite already pending => do NOT re-invite
        - else inviteFriend once.

    Returns:
      {
        "invited": bool,        # True only if we just sent inviteFriend now
        "is_friend": bool,      # True if already friend at call time
        "is_pending": bool,     # True if invite is pending (either already, or after inviteFriend)
        "external_user_id": str|None,
        "username": str|None,
      }
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
    is_friend = False
    is_pending = False

    def _match_pending(inv) -> bool:
        """Best-effort match across plexapi versions."""
        try:
            v = (
                getattr(inv, "email", None)
                or getattr(inv, "user", None)
                or getattr(inv, "username", None)
                or getattr(inv, "title", None)
                or ""
            )
            return str(v).strip().lower() == email.lower()
        except Exception:
            return False

    # 0) already friend?
    plex_user_obj = None
    try:
        plex_user_obj = account.user(email)
        invited_username = getattr(plex_user_obj, "username", None) or getattr(plex_user_obj, "title", None)
        external_user_id = getattr(plex_user_obj, "id", None)
        is_friend = True
    except Exception:
        is_friend = False

    # 0b) already pending?
    if not is_friend:
        try:
            pending_fn = getattr(account, "pendingInvites", None)
            if callable(pending_fn):
                for inv in (pending_fn() or []):
                    if _match_pending(inv):
                        is_pending = True
                        break
        except Exception:
            pass

    # 1) inviteFriend only if needed
    if (not is_friend) and (not is_pending):
        try:
            try:
                account.inviteFriend(
                    user=email,
                    server=plex,
                    sections=sections,
                    allowSync=allow_sync,
                    allowCameraUpload=allow_camera_upload,
                    allowChannels=allow_channels,
                    filterMovies=filter_movies,
                    filterTelevision=filter_television,
                    filterMusic=filter_music,
                )
            except TypeError:
                account.inviteFriend(
                    user=email,
                    server=plex,
                    sections=sections,
                )

            invited = True
            is_pending = True
            log.info(f"Plex inviteFriend OK: email={email} server={plex.friendlyName} sections={sections}")
        except Exception as e:
            log.warning(f"Plex inviteFriend failed/ignored: email={email} err={e}")

    # 2) updateFriend ONLY if already friend
    if is_friend:
        try:
            if plex_user_obj is None:
                plex_user_obj = account.user(email)

            try:
                account.updateFriend(
                    user=plex_user_obj,
                    server=plex,
                    sections=sections,
                    allowSync=allow_sync,
                    allowCameraUpload=allow_camera_upload,
                    allowChannels=allow_channels,
                    filterMovies=filter_movies,
                    filterTelevision=filter_television,
                    filterMusic=filter_music,
                )
            except TypeError:
                account.updateFriend(
                    user=plex_user_obj,
                    server=plex,
                    sections=sections,
                )

            log.info(f"Plex updateFriend OK: user={invited_username or email} server={plex.friendlyName}")
        except Exception as e:
            log.warning(f"Plex updateFriend failed: email={email} err={e}")

    return {
        "invited": bool(invited),
        "is_friend": bool(is_friend),
        "is_pending": bool(is_pending),
        "username": invited_username,
        "external_user_id": str(external_user_id) if external_user_id else None,
    }