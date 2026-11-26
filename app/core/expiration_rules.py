"""Shared date boundary, exemptions and account-level expiration eligibility."""
from datetime import date, datetime
import json

from core.plex_access_identity import is_pending_invite_media_user


def parse_expiration_date(value):
    if not value:
        return None
    text = str(value).strip().split("T", 1)[0].split(" ", 1)[0]
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def is_expired(value, today=None):
    expiration = parse_expiration_date(value)
    return expiration is not None and expiration < (today or date.today())


def account_is_protected(account):
    account = dict(account)
    provider = str(account.get("type") or "").strip().lower()
    role = str(account.get("role") or "").strip().lower()
    if provider == "plex":
        return role == "owner"
    if provider != "jellyfin":
        return False
    if role == "admin":
        return True
    try:
        payload = json.loads(account.get("raw_json") or "{}")
        policy = payload.get("Policy") if isinstance(payload, dict) else {}
        return isinstance(policy, dict) and bool(policy.get("IsAdministrator"))
    except (ValueError, TypeError):
        return False


def account_is_pending(account):
    return str(dict(account).get("type") or "").strip().lower() == "plex" and is_pending_invite_media_user(account)


def load_expiration_accounts(db, user_id):
    return [dict(row) for row in (db.query(
        """SELECT mu.id,mu.server_id,mu.type,mu.role,mu.raw_json,mu.details_json,
                  mu.accepted_at,mu.external_user_id,mu.email,mu.username
           FROM media_users mu JOIN servers s ON s.id=mu.server_id
           WHERE mu.vodum_user_id=? AND LOWER(TRIM(mu.type)) IN ('plex','jellyfin')
             AND LOWER(TRIM(mu.type))=LOWER(TRIM(s.type))""", (user_id,),
    ) or [])]


def user_is_exempt(user, accounts):
    user = dict(user)
    return (bool(user.get("expiration_date_override")) or bool(user.get("subscription_is_lifetime"))
            or any(account_is_protected(account) for account in accounts))


def only_pending_plex_accounts(db, user_id):
    accounts = load_expiration_accounts(db, user_id)
    return bool(accounts) and all(account_is_pending(account) for account in accounts)


def eligible_expiration_accounts(db, user_id):
    user = db.query_one(
        """SELECT u.expiration_date_override,u.status,COALESCE(st.is_lifetime,0) AS subscription_is_lifetime
           FROM vodum_users u LEFT JOIN subscription_templates st ON st.id=u.subscription_template_id
           WHERE u.id=?""", (user_id,),
    )
    if not user or str(user["status"] or "").lower() in ("suspended", "unfriended", "disabled", "removed"):
        return []
    accounts = load_expiration_accounts(db, user_id)
    if user_is_exempt(user, accounts):
        return []
    return [account for account in accounts if not account_is_pending(account)]
