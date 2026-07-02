"""Live provider-presence checks used before local user deletion."""

from __future__ import annotations

import json

from core.http_security import plex_server_http_session
from core.plex_connection import find_working_plex_base_url
from core.plex_rate_limit import install_plex_rate_limit
from core.providers.jellyfin_users import jellyfin_list_users
from core.providers.plex_invitation_state import matches_plex_identity


def _json_dict(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _base_url(server: dict) -> str:
    provider = str(server.get("server_type") or server.get("type") or "").lower()
    if provider == "plex":
        return find_working_plex_base_url(server, endpoint="/identity", accept="application/xml")
    return str(server.get("url") or server.get("local_url") or server.get("public_url") or "").strip().rstrip("/")


def _token(server: dict) -> str:
    return str(server.get("token") or "").strip()


def check_plex_account_presence(server: dict, account_row: dict) -> dict:
    result = {
        "provider": "plex", "state": "unknown", "exists_on_platform": False,
        "can_return_on_sync": False, "detail": "",
    }
    base = _base_url(server)
    token = _token(server)
    if not base or not token:
        result.update(detail="Plex server not fully configured", can_return_on_sync=True)
        return result

    email = str(account_row.get("email") or "").strip()
    username = str(account_row.get("username") or "").strip()
    external_user_id = str(account_row.get("external_user_id") or "").strip()
    invite_state = _json_dict(account_row.get("details_json")).get("plex_invite_state") or {}
    invite_is_pending_db = bool(invite_state.get("is_pending")) if isinstance(invite_state, dict) else False

    try:
        from plexapi.server import PlexServer

        session = plex_server_http_session(server)
        install_plex_rate_limit(session, base)
        account = PlexServer(base, token, session=session).myPlexAccount()
        try:
            users = account.users() or []
        except Exception:
            users = []
        for user in users:
            if matches_plex_identity(user, email=email, username=username, external_user_id=external_user_id):
                result.update(
                    state="friend", exists_on_platform=True, can_return_on_sync=True,
                    detail="Plex friend still exists on platform",
                )
                return result

        pending_lookup_ok = False
        try:
            pending_fn = getattr(account, "pendingInvites", None)
            pending = pending_fn() or [] if callable(pending_fn) else []
            pending_lookup_ok = callable(pending_fn)
        except Exception:
            pending = []
        for invite in pending:
            if matches_plex_identity(invite, email=email, username=username):
                result.update(
                    state="pending", exists_on_platform=True, can_return_on_sync=True,
                    detail="Pending Plex invite still exists on platform",
                )
                return result
        if invite_is_pending_db and not pending_lookup_ok:
            result.update(
                state="pending", exists_on_platform=True, can_return_on_sync=True,
                detail="Pending Plex invite flagged in database",
            )
            return result
        result.update(state="missing", detail="Plex account/invite not found on platform")
        return result
    except Exception as exc:
        result.update(can_return_on_sync=True, detail=f"Unable to verify Plex account: {exc}")
        return result


def check_jellyfin_account_presence(server: dict, account_row: dict) -> dict:
    result = {
        "provider": "jellyfin", "state": "unknown", "exists_on_platform": False,
        "can_return_on_sync": False, "detail": "",
    }
    if not _base_url(server) or not _token(server):
        result.update(detail="Jellyfin server not fully configured", can_return_on_sync=True)
        return result

    external_user_id = str(account_row.get("external_user_id") or "").strip()
    username = str(account_row.get("username") or "").strip().lower()
    email = str(account_row.get("email") or "").strip().lower()
    try:
        for user in jellyfin_list_users(server) or []:
            native_id = str(user.get("Id") or "").strip()
            native_name = str(user.get("Name") or "").strip().lower()
            if (
                (external_user_id and native_id == external_user_id)
                or (username and native_name == username)
                or (email and native_name == email)
            ):
                result.update(
                    state="present", exists_on_platform=True, can_return_on_sync=True,
                    detail="Jellyfin user still exists on platform",
                )
                return result
        result.update(state="missing", detail="Jellyfin user not found on platform")
        return result
    except Exception as exc:
        result.update(can_return_on_sync=True, detail=f"Unable to verify Jellyfin user: {exc}")
        return result


def get_user_deletion_protection(db, user_id: int) -> dict:
    columns = {
        str(row["name"])
        for row in (db.query("PRAGMA table_info(media_users)") or [])
    }
    role_payload_column = "mu.raw_json" if "raw_json" in columns else "mu.details_json"
    rows = db.query(
        f"""
        SELECT s.type AS server_type, mu.role, {role_payload_column} AS role_json
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
        """,
        (int(user_id),),
    ) or []
    for raw in rows:
        row = dict(raw)
        provider = str(row.get("server_type") or "").strip().lower()
        role = str(row.get("role") or "").strip().lower()
        if provider == "plex" and role == "owner":
            return {"can_delete": False, "protected_role": "owner", "blocked_reason": "plex_owner_cannot_be_deleted"}
        if provider == "jellyfin":
            payload = _json_dict(row.get("role_json"))
            policy = payload.get("Policy") if isinstance(payload, dict) else {}
            if role == "admin" or (isinstance(policy, dict) and policy.get("IsAdministrator")):
                return {"can_delete": False, "protected_role": "admin", "blocked_reason": "remove_admin_to_delete"}
    return {"can_delete": True, "protected_role": "", "blocked_reason": ""}


def build_user_delete_check(db, user_id: int) -> dict | None:
    user = db.query_one("SELECT id,username,email FROM vodum_users WHERE id=?", (int(user_id),))
    if not user:
        return None
    rows = db.query(
        """
        SELECT mu.id,mu.server_id,mu.external_user_id,mu.username,mu.email,mu.type,mu.role,
               mu.joined_at,mu.accepted_at,mu.details_json,
               s.name AS server_name,s.type AS server_type,s.url,s.local_url,s.public_url,s.token
        FROM media_users mu
        JOIN servers s ON s.id=mu.server_id
        WHERE mu.vodum_user_id=?
        ORDER BY s.type,s.name,mu.id
        """,
        (int(user_id),),
    ) or []
    protection = get_user_deletion_protection(db, user_id)
    items = []
    totals = {"still_exists_total": 0, "pending_total": 0, "unknown_total": 0}
    will_return = False
    for raw in rows:
        row = dict(raw)
        provider = str(row.get("type") or row.get("server_type") or "").strip().lower()
        if provider == "plex":
            live = check_plex_account_presence(row, row)
        elif provider == "jellyfin":
            live = check_jellyfin_account_presence(row, row)
        else:
            live = {
                "state": "unknown", "exists_on_platform": False, "can_return_on_sync": True,
                "detail": f"Unsupported provider: {provider or 'unknown'}",
            }
        totals["still_exists_total"] += int(bool(live["exists_on_platform"]))
        totals["pending_total"] += int(live["state"] == "pending")
        totals["unknown_total"] += int(live["state"] == "unknown")
        will_return = will_return or bool(live["can_return_on_sync"])
        items.append({
            "media_user_id": int(row["id"]), "provider": provider or "unknown",
            "server_name": row["server_name"] or "", "username": row["username"] or "",
            "email": row["email"] or "", "external_user_id": row["external_user_id"] or "",
            "accepted_at": row["accepted_at"] or "", "state": live["state"],
            "exists_on_platform": bool(live["exists_on_platform"]),
            "can_return_on_sync": bool(live["can_return_on_sync"]), "detail": live["detail"],
        })
    return {
        "ok": True, "user_id": int(user["id"]), "username": user["username"] or "",
        "email": user["email"] or "", "linked_accounts_total": len(rows),
        **protection,
        **totals, "will_return_on_sync": will_return, "items": items,
    }
