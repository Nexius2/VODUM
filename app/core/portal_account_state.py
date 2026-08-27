from __future__ import annotations


PORTAL_ACCESSIBLE_STATE = "active"


def effective_portal_account_state(account_status, user_status) -> str:
    account = str(account_status or "invited").strip().lower()
    user = str(user_status or "").strip().lower()
    if account == "deleted":
        return "deleted"
    if account == "suspended":
        return "suspended"
    if account == "invited":
        return "invited"
    if user == "expired":
        return "expired"
    if user == "suspended":
        return "suspended"
    return "active"


def state_allows_portal(account_status, user_status) -> bool:
    return effective_portal_account_state(account_status, user_status) == PORTAL_ACCESSIBLE_STATE


def state_message(state: str) -> str:
    return {
        "invited": "portal_state_invited",
        "active": "portal_state_active",
        "suspended": "portal_state_suspended",
        "expired": "portal_state_expired",
        "deleted": "portal_state_deleted",
    }.get(str(state or ""), "portal_unavailable")


def ensure_provider_portal_account(db, vodum_user_id: int) -> int | None:
    """Create/activate the portal account after a trusted provider login.

    Suspended and deleted accounts remain blocked. An invited account may become
    active because Plex/Jellyfin has just verified the user's provider identity.
    """
    user_id = int(vodum_user_id)
    account = db.query_one("SELECT id,status FROM portal_accounts WHERE vodum_user_id=?", (user_id,))
    account_status = str(dict(account).get("status") or "active").lower() if account else ""
    if account and account_status in {"suspended", "deleted"}:
        return None
    if not account:
        db.execute(
            "INSERT INTO portal_accounts(vodum_user_id,status) VALUES(?,'active') "
            "ON CONFLICT(vodum_user_id) DO NOTHING",
            (user_id,),
        )
        account = db.query_one("SELECT id,status FROM portal_accounts WHERE vodum_user_id=?", (user_id,))
    elif account_status == "invited":
        db.execute(
            "UPDATE portal_accounts SET status='active',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='invited'",
            (int(account["id"]),),
        )
    if not account:
        return None
    account_id = int(account["id"])
    db.execute(
        "INSERT OR IGNORE INTO portal_account_roles(portal_account_id,role_id) "
        "SELECT ?,id FROM portal_roles WHERE name='user'",
        (account_id,),
    )
    return account_id
