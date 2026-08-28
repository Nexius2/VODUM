from __future__ import annotations


PORTAL_ADMIN_ACTIONS = {"revoke_invitation", "suspend", "reactivate", "force_logout", "reset_auth"}


def load_portal_admin_context(db, vodum_user_id: int) -> dict:
    account = db.query_one(
        "SELECT id,status,email_verified_at,last_login_at,created_at,updated_at "
        "FROM portal_accounts WHERE vodum_user_id=?",
        (int(vodum_user_id),),
    )
    if not account:
        return {"account": None, "identities": [], "roles": [], "pending_invitations": [], "audit": [], "active_sessions": 0}
    account = dict(account)
    account_id = int(account["id"])
    identities = db.query(
        "SELECT provider,normalized_identifier,is_active,verified_at,created_at "
        "FROM portal_auth_identities WHERE portal_account_id=? ORDER BY provider,created_at",
        (account_id,),
    ) or []
    roles = db.query(
        "SELECT pr.name FROM portal_account_roles par JOIN portal_roles pr ON pr.id=par.role_id "
        "WHERE par.portal_account_id=? ORDER BY pr.name",
        (account_id,),
    ) or []
    invitations = db.query(
        "SELECT id,created_at,expires_at FROM portal_account_tokens "
        "WHERE portal_account_id=? AND purpose='invitation' AND used_at IS NULL "
        "AND revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP ORDER BY created_at DESC",
        (account_id,),
    ) or []
    session_row = db.query_one(
        "SELECT COUNT(*) AS count FROM portal_sessions WHERE portal_account_id=? "
        "AND revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP",
        (account_id,),
    ) or {}
    session_row = dict(session_row)
    audit = db.query(
        "SELECT event_type,outcome,details_json,created_at FROM portal_audit_events "
        "WHERE portal_account_id=? ORDER BY created_at DESC,id DESC LIMIT 25",
        (account_id,),
    ) or []
    return {
        "account": account,
        "identities": [dict(row) for row in identities],
        "roles": [row["name"] for row in roles],
        "pending_invitations": [dict(row) for row in invitations],
        "active_sessions": int(session_row.get("count") or 0),
        "audit": [dict(row) for row in audit],
    }


def apply_portal_admin_action(db, vodum_user_id: int, action: str) -> int:
    if action not in PORTAL_ADMIN_ACTIONS:
        raise ValueError("portal_admin_action_invalid")
    account = db.query_one("SELECT id,status FROM portal_accounts WHERE vodum_user_id=?", (int(vodum_user_id),))
    if not account:
        raise ValueError("portal_account_missing")
    account_id = int(account["id"])
    with db.transaction() as cursor:
        if action == "revoke_invitation":
            cursor.execute(
                "UPDATE portal_account_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE portal_account_id=? "
                "AND purpose='invitation' AND used_at IS NULL AND revoked_at IS NULL",
                (account_id,),
            )
        elif action == "suspend":
            cursor.execute("UPDATE portal_accounts SET status='suspended',updated_at=CURRENT_TIMESTAMP WHERE id=?", (account_id,))
            cursor.execute(
                "UPDATE portal_sessions SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP),"
                "revoke_reason=COALESCE(revoke_reason,'account_suspended') WHERE portal_account_id=?",
                (account_id,),
            )
        elif action == "reactivate":
            if account["status"] != "suspended":
                raise ValueError("portal_account_not_suspended")
            cursor.execute("UPDATE portal_accounts SET status='active',updated_at=CURRENT_TIMESTAMP WHERE id=?", (account_id,))
        elif action == "force_logout":
            cursor.execute(
                "UPDATE portal_sessions SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP),"
                "revoke_reason=COALESCE(revoke_reason,'admin_forced_logout') WHERE portal_account_id=?",
                (account_id,),
            )
        elif action == "reset_auth":
            cursor.execute(
                "UPDATE portal_auth_identities SET is_active=0,password_hash=NULL,verified_at=NULL,revoked_at=CURRENT_TIMESTAMP,revoke_reason='admin_reset',updated_at=CURRENT_TIMESTAMP "
                "WHERE portal_account_id=?",
                (account_id,),
            )
            cursor.execute(
                "UPDATE portal_account_tokens SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP) "
                "WHERE portal_account_id=? AND used_at IS NULL",
                (account_id,),
            )
            cursor.execute(
                "UPDATE portal_sessions SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP),"
                "revoke_reason=COALESCE(revoke_reason,'admin_auth_reset') WHERE portal_account_id=?",
                (account_id,),
            )
            cursor.execute("UPDATE portal_accounts SET status='invited',email_verified_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (account_id,))
    return account_id
