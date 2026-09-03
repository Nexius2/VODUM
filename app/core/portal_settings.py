from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PortalSettingsResult:
    values: dict
    errors: tuple[str, ...]


def _valid_email(value: str) -> bool:
    if not value or " " in value or value.count("@") != 1:
        return False
    local, domain = value.rsplit("@", 1)
    return bool(local and "." in domain and not domain.startswith("."))


def normalize_portal_settings(form, *, activation_ready=False, debug_mode=False) -> PortalSettingsResult:
    public_url = str(form.get("portal_public_url") or "").strip().rstrip("/")
    parsed_public = urlsplit(public_url) if public_url else None
    allowed_hostname = parsed_public.hostname if parsed_public else None
    payment_url = str(form.get("portal_payment_url") or "").strip()
    payment_label = str(form.get("portal_payment_label") or "").strip()[:100]
    support_content = str(form.get("portal_support_content") or "").strip()[:5000]
    requested_enabled = str(form.get("portal_enabled") or "") == "1"
    try:
        password_min_length = max(8, min(128, int(form.get("portal_password_min_length") or 8)))
    except (TypeError, ValueError):
        password_min_length = 8
    values = {
        "portal_enabled": 0,
        "portal_local_test_enabled": 1 if form.get("portal_local_test_enabled") == "1" else 0,
        "portal_public_url": public_url or None,
        "portal_allowed_hostname": allowed_hostname or None,
        "portal_show_subscription": 1 if form.get("portal_show_subscription") == "1" else 0,
        "portal_show_media_access": 1 if form.get("portal_show_media_access") == "1" else 0,
        "portal_show_monitoring": 1 if form.get("portal_show_monitoring") == "1" else 0,
        "portal_show_support": 1 if form.get("portal_show_support") == "1" else 0,
        "portal_support_content": support_content or None,
        "portal_show_support_email": 1 if form.get("portal_show_support_email") == "1" else 0,
        "portal_quick_messages_enabled": 1 if form.get("portal_quick_messages_enabled") == "1" else 0,
        # Experimental: the switch cannot be persisted outside debug mode.
        "portal_show_payment": 1 if debug_mode and form.get("portal_show_payment") == "1" else 0,
        "portal_payment_url": payment_url or None,
        "portal_payment_label": payment_label or None,
        "portal_local_auth_enabled": 1 if form.get("portal_local_auth_enabled") == "1" else 0,
        "portal_plex_auth_enabled": 1 if form.get("portal_plex_auth_enabled") == "1" else 0,
        "portal_jellyfin_auth_enabled": 1 if form.get("portal_jellyfin_auth_enabled") == "1" else 0,
        "portal_password_min_length": password_min_length,
        "portal_password_require_upper": 1 if form.get("portal_password_require_upper") == "1" else 0,
        "portal_password_require_lower": 1 if form.get("portal_password_require_lower") == "1" else 0,
        "portal_password_require_digit": 1 if form.get("portal_password_require_digit") == "1" else 0,
        "portal_password_require_symbol": 1 if form.get("portal_password_require_symbol") == "1" else 0,
    }
    errors = []
    if public_url:
        parsed = urlsplit(public_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            errors.append("portal_public_url_invalid")
        elif parsed.query or parsed.fragment:
            errors.append("portal_public_url_invalid")
    if payment_url:
        parsed_payment = urlsplit(payment_url)
        if parsed_payment.scheme != "https" or not parsed_payment.netloc or parsed_payment.username or parsed_payment.fragment:
            errors.append("portal_payment_url_invalid")
    if requested_enabled:
        if activation_ready:
            values["portal_enabled"] = 1
        else:
            errors.append("portal_activation_not_ready")
    return PortalSettingsResult(values=values, errors=tuple(errors))
