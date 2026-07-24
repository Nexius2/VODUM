from core.communication_i18n import normalize_communication_language
from core.communication_template_admin import encrypted_secret_from_form, sanitize_notifications_order
from core.smtp_settings import normalize_smtp_auth_method
from secret_store import encrypt_secret


def _optional_int(value):
    try:
        return int(value)
    except Exception:
        return None


def parse_communication_configuration(form, settings: dict) -> dict:
    smtp_pass = encrypted_secret_from_form(form.get("smtp_pass"), settings.get("smtp_pass"), empty_existing="")
    oauth_token = encrypted_secret_from_form(
        form.get("smtp_oauth_access_token"), settings.get("smtp_oauth_access_token"), empty_existing=None,
    )
    auth_method = str(form.get("smtp_auth_method") or "password").strip().lower()
    if auth_method not in ("password", "oauth2"):
        auth_method = "password"
    auth_method = normalize_smtp_auth_method(auth_method, settings, smtp_pass, oauth_token)
    discord_raw = form.get("discord_bot_token")
    discord_token = encrypt_secret((discord_raw or "").strip() or None)
    if discord_raw is not None and not discord_raw.strip():
        discord_token = settings.get("discord_bot_token") or None
    send_mode = str(form.get("notifications_send_mode") or settings.get("notifications_send_mode") or "first").strip().lower()
    if send_mode not in ("first", "all"):
        send_mode = "first"
    return {
        "mailing_enabled": int(form.get("mailing_enabled") == "1"),
        "skip_never_used_accounts": int(form.get("skip_never_used_accounts") == "1"),
        "mail_from": str(form.get("mail_from") or "").strip() or None,
        "smtp_host": str(form.get("smtp_host") or "").strip() or None,
        "smtp_port": _optional_int(form.get("smtp_port")),
        "smtp_tls": int(form.get("smtp_tls") == "1"),
        "smtp_user": str(form.get("smtp_user") or "").strip() or None,
        "smtp_pass": smtp_pass,
        "smtp_auth_method": auth_method,
        "smtp_oauth_access_token": oauth_token,
        "discord_enabled": int(form.get("discord_enabled") == "1"),
        "discord_bot_token": discord_token,
        "notifications_send_mode": send_mode,
        "notifications_order": sanitize_notifications_order(
            form.get("notifications_order") or settings.get("notifications_order") or "email"
        ),
        "user_notifications_can_override": int(form.get("user_notifications_can_override") == "1"),
        "communication_language": normalize_communication_language(
            form.get("communication_language") or settings.get("communication_language") or "en"
        ),
    }
