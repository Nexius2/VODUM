from logging_utils import get_logger
from core.providers.jellyfin_users import (
    jellyfin_create_user,
    jellyfin_reset_password_required,
    jellyfin_set_password,
    jellyfin_set_policy_folders,
)
from core.providers.plex_invitation_state import plex_invite_state_payload
from core.providers.plex_users import plex_invite_and_share
from secret_store import find_plex_servers_by_token


log = get_logger("users_create")


def provision_provider_account(db, server, block, libraries, username, email):
    server_id = int(server["id"])
    provider = (server.get("type") or "").lower()
    details_json = {}

    if provider == "jellyfin":
        existing = db.query_one(
            """
            SELECT 1 FROM media_users
            WHERE server_id = ? AND type = 'jellyfin' AND lower(username) = lower(?)
            """,
            (server_id, username),
        )
        if existing:
            raise RuntimeError(f"Jellyfin: username already exists on server '{server.get('name')}'")
        created = jellyfin_create_user(server, username)
        external_user_id = str(created.get("Id"))
        server_username = created.get("Name") or username
        password = (block.get("jellyfin_password") or "").strip()
        force_change = bool(block.get("jellyfin_force_password_change"))
        if password:
            jellyfin_set_password(server, external_user_id, password)
            jellyfin_reset_password_required(server, external_user_id, force_change)
        enabled_folders = [str(library["section_id"]) for library in libraries]
        jellyfin_set_policy_folders(
            server,
            external_user_id,
            enabled_folders,
            force_password_change=force_change,
        )
        details_json["jellyfin"] = {
            "enabled_folders": enabled_folders,
            "force_password_change": force_change,
        }
        return external_user_id, server_username, details_json

    if provider != "plex":
        raise RuntimeError(f"Unsupported server type '{provider}'")
    if not email:
        raise RuntimeError("Plex: email is required")

    token = server.get("token") or ""
    group_servers = (find_plex_servers_by_token(db, token) or [server]) if token else [server]
    libraries_by_server = {}
    for library in libraries:
        libraries_by_server.setdefault(int(library["server_id"]), []).append(library)
    flags = block.get("plex_share") or {}
    invite_kwargs = {
        "email": email,
        "allow_sync": bool(flags.get("allowSync")),
        "allow_camera_upload": bool(flags.get("allowCameraUpload")),
        "allow_channels": bool(flags.get("allowChannels")),
        "filter_movies": str(flags.get("filterMovies") or ""),
        "filter_television": str(flags.get("filterTelevision") or ""),
        "filter_music": str(flags.get("filterMusic") or ""),
    }
    primary_server_id = server_id
    if primary_server_id not in libraries_by_server:
        primary_server_id = int(next(iter(libraries_by_server.keys())))
    invite_state = {"is_friend": False, "is_pending": False}
    external_user_id = None
    server_username = None
    primary_server = next(
        (item for item in group_servers if int(item.get("id")) == primary_server_id),
        None,
    )
    if primary_server is not None:
        selected = libraries_by_server.get(primary_server_id, [])
        if selected:
            log.info(
                f"[PLEX INVITE] server={primary_server.get('name')} "
                f"email={email} libs={[item['name'] for item in selected]}"
            )
            print(
                f"[PLEX INVITE STDOUT] server={primary_server.get('name')} "
                f"email={email} libs={[item['name'] for item in selected]}",
                flush=True,
            )
            invite_state = plex_invite_and_share(
                primary_server,
                libraries_names=[item["name"] for item in selected],
                **invite_kwargs,
            )
            log.info(f"[PLEX INVITE RESULT] {invite_state}")
            print(f"[PLEX INVITE RESULT STDOUT] {invite_state}", flush=True)
            external_user_id = invite_state.get("external_user_id") or external_user_id
            server_username = invite_state.get("username") or server_username

    if invite_state.get("is_friend"):
        for linked_server in group_servers:
            linked_id = int(linked_server["id"])
            selected = libraries_by_server.get(linked_id, [])
            if linked_id == primary_server_id or not selected:
                continue
            log.info(
                f"[PLEX INVITE LINKED] server={linked_server.get('name')} "
                f"email={email} libs={[item['name'] for item in selected]}"
            )
            linked_state = plex_invite_and_share(
                linked_server,
                libraries_names=[item["name"] for item in selected],
                **invite_kwargs,
            )
            log.info(f"[PLEX INVITE LINKED RESULT] {linked_state}")
            external_user_id = external_user_id or linked_state.get("external_user_id")
            server_username = server_username or linked_state.get("username")

    state = (
        "friend" if invite_state.get("is_friend")
        else "pending" if invite_state.get("is_pending")
        else "unknown"
    )
    details_json["plex_invite_state"] = plex_invite_state_payload(
        state,
        primary_server_id=primary_server_id,
    )
    details_json["plex_linked_servers"] = [
        {"id": int(item["id"]), "name": item.get("name")} for item in group_servers
    ]
    return external_user_id, server_username, details_json
