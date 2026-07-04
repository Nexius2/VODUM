from datetime import datetime, date
import re

ALLOWED_VARS = {
    "username",
    "firstusername",
    "email",
    "expiration_date",
    "days_left",
    "brand_name",

    "firstname",
    "lastname",
    "server_name",
    "server_url",
    "login_username",
    "temporary_password",

    "subscription_name",
    "subscription_value",
    "subscription_price",
    "subscription_duration_days",
    "duration_days",
    "current_subscription",
    "suggested_subscription",

    "old_expiration_date",
    "new_expiration_date",
    "expiration_change_days",
    "expiration_change_signed_days",
    "expiration_change_direction",
    "expiration_change_reason",

    "referred_username",
    "referral_reward_days",
    "referrer_old_expiration_date",
    "referrer_new_expiration_date",

    "policy_name",
    "policy_reason",
    "media_title",
    "client_name",
    "device_name",
    "blocked_at",
    "policy_rule_type",
    "policy_limit",
    "policy_observed",
    "maximum_streams",
    "maximum_ips",
    "stream_count",
    "ip_count",
    "stream_killed",
    "other_streams_count",
    "other_streams",
    "all_streams",
    "policy_explanation",
    "policy_limit_label",
    "active_streams_count",
    "active_streams",
    "active_ips_count",
    "active_ips",
    "active_devices_count",
    "active_devices",

    "usage_risk_level",
    "usage_risk_score",
    "usage_risk_main_reason",
    "usage_risk_reasons",
    "usage_risk_kills_7d",
    "usage_risk_kills_30d",
    "usage_risk_kills_90d",
}


def _fmt_value(value):
    if value is None:
        return ""

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    return str(value)


def build_user_context(user: dict):
    today = date.today()

    expiration = user.get("expiration_date")
    days_left = ""

    if expiration:
        try:
            exp_date = datetime.fromisoformat(str(expiration)).date()
            days_left = str((exp_date - today).days)
        except Exception:
            days_left = ""

    username = user.get("username", "") or ""
    firstname = user.get("firstname", "") or ""

    subscription_name = user.get("subscription_name", "") or ""
    subscription_value = _fmt_value(user.get("subscription_value", ""))
    subscription_duration_days = _fmt_value(user.get("subscription_duration_days", ""))

    current_subscription = (
        user.get("current_subscription")
        or subscription_name
        or ""
    )

    return {
        "username": username,
        "firstusername": firstname or username,
        "email": user.get("email", "") or "",
        "expiration_date": str(expiration) if expiration else "",
        "days_left": days_left,
        "brand_name": user.get("brand_name", "") or "VODUM",

        "firstname": firstname,
        "lastname": user.get("lastname", "") or "",
        "server_name": user.get("server_name", "") or "",
        "server_url": user.get("server_url", "") or "",
        "login_username": user.get("login_username", "") or username,
        "temporary_password": user.get("temporary_password", "") or "",

        "subscription_name": subscription_name,
        "subscription_value": subscription_value,
        "subscription_price": subscription_value,
        "subscription_duration_days": subscription_duration_days,
        "duration_days": subscription_duration_days,
        "current_subscription": current_subscription,
        "suggested_subscription": user.get("suggested_subscription", "") or "",

        "old_expiration_date": user.get("old_expiration_date", "") or "",
        "new_expiration_date": user.get("new_expiration_date", "") or "",
        "expiration_change_days": user.get("expiration_change_days", "") or "",
        "expiration_change_signed_days": user.get("expiration_change_signed_days", "") or "",
        "expiration_change_direction": user.get("expiration_change_direction", "") or "",
        "expiration_change_reason": user.get("expiration_change_reason", "") or "",

        "referred_username": user.get("referred_username", "") or "",
        "referral_reward_days": user.get("referral_reward_days", "") or "",
        "referrer_old_expiration_date": user.get("referrer_old_expiration_date", "") or "",
        "referrer_new_expiration_date": user.get("referrer_new_expiration_date", "") or "",

        "policy_name": user.get("policy_name", "") or "",
        "policy_reason": user.get("policy_reason", "") or "",
        "media_title": user.get("media_title", "") or "",
        "client_name": user.get("client_name", "") or "",
        "device_name": user.get("device_name", "") or "",
        "blocked_at": user.get("blocked_at", "") or "",
        "policy_rule_type": user.get("policy_rule_type", "") or "",
        "policy_limit": user.get("policy_limit", "") or "",
        "policy_observed": user.get("policy_observed", "") or "",
        "maximum_streams": user.get("maximum_streams", "") or "",
        "maximum_ips": user.get("maximum_ips", "") or "",
        "stream_count": user.get("stream_count", "") or "",
        "ip_count": user.get("ip_count", "") or "",
        "stream_killed": user.get("stream_killed", "") or "",
        "other_streams_count": user.get("other_streams_count", "") or "",
        "other_streams": user.get("other_streams", "") or "",
        "all_streams": user.get("all_streams", "") or "",
        "policy_explanation": user.get("policy_explanation", "") or "",
        "policy_limit_label": user.get("policy_limit_label", "") or "",
        "active_streams_count": user.get("active_streams_count", "") or "",
        "active_streams": user.get("active_streams", "") or "",
        "active_ips_count": user.get("active_ips_count", "") or "",
        "active_ips": user.get("active_ips", "") or "",
        "active_devices_count": user.get("active_devices_count", "") or "",
        "active_devices": user.get("active_devices", "") or "",

        "usage_risk_level": user.get("usage_risk_level", "") or "",
        "usage_risk_score": user.get("usage_risk_score", "") or "",
        "usage_risk_main_reason": user.get("usage_risk_main_reason", "") or "",
        "usage_risk_reasons": user.get("usage_risk_reasons", "") or "",
        "usage_risk_kills_7d": user.get("usage_risk_kills_7d", "") or "",
        "usage_risk_kills_30d": user.get("usage_risk_kills_30d", "") or "",
        "usage_risk_kills_90d": user.get("usage_risk_kills_90d", "") or "",
    }


def render_mail(text: str, context: dict) -> str:
    if not text:
        return ""

    context = context or {}

    for key in ALLOWED_VARS:
        value = context.get(key, "")
        text = text.replace(f"{{{key}}}", _fmt_value(value))

    def replace_dynamic_var(match):
        key = match.group(1)
        return _fmt_value(context.get(key, ""))

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace_dynamic_var, text)
