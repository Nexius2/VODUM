import re

from core.plex_share_xml import get_shared_servers_for_machine


def find_shared_server_id_for_user(account, machine_id: str, plex_user) -> str | None:
    normalize = lambda value: str(value or "").strip()
    lower = lambda value: normalize(value).lower()
    target_uid = normalize(getattr(plex_user, "id", None))
    target_username = lower(getattr(plex_user, "username", None))
    target_email = lower(getattr(plex_user, "email", None))
    target_title = lower(getattr(plex_user, "title", None))
    for shared in get_shared_servers_for_machine(account, machine_id):
        if target_uid and target_uid in (
            normalize(shared.get("userID")),
            normalize(shared.get("invitedId")),
        ):
            return shared.get("id")
        if target_username and lower(shared.get("username")) == target_username:
            return shared.get("id")
        if target_email and lower(shared.get("email")) == target_email:
            return shared.get("id")
        if target_title and lower(shared.get("username")) == target_title:
            return shared.get("id")
    return None


def find_shared_server_state_for_user(account, machine_id: str, plex_user):
    shared_id = find_shared_server_id_for_user(account, machine_id, plex_user)
    if not shared_id:
        return None
    for shared in get_shared_servers_for_machine(account, machine_id):
        if str(shared.get("id") or "").strip() == str(shared_id):
            return shared
    return {"id": shared_id, "section_ids": []}


def extract_already_shared_username(error_message: str) -> str | None:
    match = re.search(
        r"already sharing this server with\s+([^.<>]+)",
        str(error_message or ""),
        re.IGNORECASE,
    )
    return match.group(1).strip().lower() or None if match else None
