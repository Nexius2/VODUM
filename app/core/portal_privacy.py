from __future__ import annotations


def export_portal_user_data(db, vodum_user_id: int) -> dict | None:
    user = db.query_one(
        "SELECT id,username,firstname,lastname,email,second_email,status,created_at,expiration_date,renewal_date "
        "FROM vodum_users WHERE id=?", (int(vodum_user_id),),
    )
    if not user:
        return None
    account = db.query_one(
        "SELECT id,status,email_verified_at,last_login_at,created_at,updated_at FROM portal_accounts WHERE vodum_user_id=?",
        (int(vodum_user_id),),
    )
    account_id = int(account["id"]) if account else None
    identities = db.query(
        "SELECT provider,provider_server_id,normalized_identifier,is_active,verified_at,last_login_at,created_at "
        "FROM portal_auth_identities WHERE portal_account_id=?", (account_id,),
    ) if account_id else []
    media = db.query(
        "SELECT mu.type,mu.username,mu.email,mu.joined_at,mu.accepted_at,s.name AS server_name "
        "FROM media_users mu JOIN servers s ON s.id=mu.server_id WHERE mu.vodum_user_id=?",
        (int(vodum_user_id),),
    ) or []
    libraries = db.query(
        "SELECT s.name AS server_name,l.name,l.type FROM media_user_libraries mul "
        "JOIN media_users mu ON mu.id=mul.media_user_id JOIN libraries l ON l.id=mul.library_id "
        "JOIN servers s ON s.id=l.server_id WHERE mu.vodum_user_id=?",
        (int(vodum_user_id),),
    ) or []
    audit = db.query(
        "SELECT event_type,outcome,details_json,created_at FROM portal_audit_events "
        "WHERE portal_account_id=? ORDER BY created_at", (account_id,),
    ) if account_id else []
    return {"format": "vodum-portal-user-export", "version": 1, "user": dict(user),
            "portal_account": dict(account) if account else None,
            "identities": [dict(row) for row in identities], "media_accounts": [dict(row) for row in media],
            "libraries": [dict(row) for row in libraries], "audit": [dict(row) for row in audit]}


def erase_portal_user_data(db, vodum_user_id: int) -> bool:
    account = db.query_one("SELECT id FROM portal_accounts WHERE vodum_user_id=?", (int(vodum_user_id),))
    if not account:
        return False
    account_id = int(account["id"])
    with db.transaction() as cursor:
        cursor.execute("DELETE FROM portal_audit_events WHERE portal_account_id=?", (account_id,))
        cursor.execute("DELETE FROM portal_accounts WHERE id=?", (account_id,))
    return True


def cleanup_portal_retention(db, cutoff_iso: str) -> dict:
    deleted = {}
    statements = (
        ("sessions", "DELETE FROM portal_sessions WHERE expires_at<?", (cutoff_iso,)),
        ("tokens", "DELETE FROM portal_account_tokens WHERE expires_at<?", (cutoff_iso,)),
        ("audit", "DELETE FROM portal_audit_events WHERE created_at<?", (cutoff_iso,)),
        ("rate_limits", "DELETE FROM portal_request_limits WHERE window_started_at<?", (cutoff_iso,)),
        ("login_attempts", "DELETE FROM portal_login_attempts WHERE last_failed_at IS NOT NULL AND last_failed_at<?", (cutoff_iso,)),
    )
    for label, sql, params in statements:
        cursor = db.execute(sql, params)
        deleted[label] = max(int(getattr(cursor, "rowcount", 0) or 0), 0)
    return deleted
