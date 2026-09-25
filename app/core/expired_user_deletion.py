"""Expiration deletion: preflight all accounts, delete remotely, then locally."""
from datetime import date
import json

from secret_store import decrypt_server_record
from core.native_user_deletion import NativeUserDeletion, NativeDeletionError
from core.user_deletion import delete_local_user
from core.expiration_rules import parse_expiration_date


def delete_expired_user(db, user_id, *, today=None, adapter=NativeUserDeletion):
    today = today or date.today()
    result = {"status": "skipped", "confirmed": [], "reason": "not_eligible"}
    targets = []
    try:
        # Serialize eligibility/renewal, account changes and final local deletion.
        # No DBManager calls from inside this transaction (its lock is not recursive).
        with db.transaction() as cur:
            settings = cur.execute(
                "SELECT expiry_mode,delete_after_expiry_days,enable_cron_jobs FROM settings WHERE id=1"
            ).fetchone()
            if not settings or settings["expiry_mode"] != "delete" or not settings["enable_cron_jobs"]:
                return result
            try:
                delay = int(settings["delete_after_expiry_days"])
            except (ValueError, TypeError):
                return result
            if not 1 <= delay <= 3650:
                return result
            user = cur.execute(
                """SELECT u.expiration_date,u.expiration_date_override,u.status,
                          COALESCE(st.is_lifetime,0) AS lifetime
                   FROM vodum_users u LEFT JOIN subscription_templates st ON st.id=u.subscription_template_id
                   WHERE u.id=?""", (user_id,),
            ).fetchone()
            if not user or user["expiration_date_override"] or user["lifetime"]:
                return result
            if str(user["status"] or "").lower() not in ("active", "pre_expired", "reminder", "expired"):
                return result
            expiration = parse_expiration_date(user["expiration_date"])
            if expiration is None or expiration >= today or (today - expiration).days < delay:
                return result
            accounts = [dict(row) for row in cur.execute(
                "SELECT id,server_id,type,external_user_id,role,raw_json,details_json FROM media_users WHERE vodum_user_id=? ORDER BY server_id,id",
                (user_id,),
            ).fetchall()]
            if not accounts:
                result["reason"] = "no_native_account"
                return result
            if cur.execute(
                "SELECT id FROM media_jobs WHERE vodum_user_id=? AND status='running' AND processed=0 LIMIT 1",
                (user_id,),
            ).fetchone():
                result["reason"] = "native_job_running"
                return result
            try:
                # Preflight every server before performing any destructive request.
                for account in accounts:
                    if str(account.get("role") or "").lower() in ("owner", "admin", "home") or not str(account.get("external_user_id") or "").strip():
                        result["reason"] = "protected_or_pending_account"
                        return result
                    payload = json.loads(account.get("raw_json") or "{}")
                    policy = payload.get("Policy", {}) if isinstance(payload, dict) else {}
                    if isinstance(policy, dict) and policy.get("IsAdministrator"):
                        result["reason"] = "protected_administrator"
                        return result
                    details = json.loads(account.get("details_json") or "{}")
                    invite = details.get("plex_invite_state", {}) if isinstance(details, dict) else {}
                    if isinstance(invite, dict) and invite.get("is_pending"):
                        result["reason"] = "pending_invitation"
                        return result
                    row = cur.execute(
                        "SELECT id,type,url,local_url,public_url,token,server_identifier,settings_json FROM servers WHERE id=?",
                        (account["server_id"],),
                    ).fetchone()
                    if not row or str(row["type"]).lower() != str(account["type"]).lower():
                        raise NativeDeletionError("Missing or mismatched server")
                    server = dict(decrypt_server_record(row))
                    target = adapter(account, server)
                    targets.append(target)
                    target.inspect()
                # Prevent a queued grant/sync from undoing a partially completed deletion.
                cur.execute(
                    """UPDATE media_jobs SET status='canceled',processed=1,success=0,
                           processed_at=CURRENT_TIMESTAMP,last_error='Canceled by expiration deletion'
                       WHERE vodum_user_id=? AND processed=0 AND status='queued'""", (user_id,),
                )
                for account, target in zip(accounts, targets):
                    target.delete_and_confirm()
                    result["confirmed"].append({"server_id": account["server_id"], "media_user_id": account["id"]})
            except Exception as exc:
                # Keep local identities on partial failure. Next run rechecks native state.
                # Commit canceled queued jobs even when a server operation failed.
                result.update(status="failed", reason=str(exc) if isinstance(exc, NativeDeletionError) else type(exc).__name__)
                return result
            delete_local_user(cur, user_id)
            result.update(status="deleted", reason="all_native_accounts_confirmed")
            return result
    finally:
        for target in targets:
            target.close()
