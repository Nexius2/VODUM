from __future__ import annotations

from typing import List, Dict


SUPPORTED_CHANNELS = ("discord", "email")


def parse_notifications_order(value: str | None) -> List[str]:
    """Parse settings.notifications_order.

    Accepts strings like:
      - "discord"
      - "email"
      - "discord,email"
      - "email,discord"

    Unknown channels are ignored to keep the system forward-compatible.
    """
    if not value:
        return ["email"]
    parts = []
    for raw in (value or "").split(","):
        p = (raw or "").strip().lower()
        if not p:
            continue
        if p in SUPPORTED_CHANNELS and p not in parts:
            parts.append(p)
    return parts or ["email"]


def normalize_notifications_order(settings: Dict) -> List[str]:
    return parse_notifications_order((settings or {}).get("notifications_order"))


def is_email_ready(settings: Dict) -> bool:
    if not settings:
        return False
    try:
        return bool(
            int(settings.get("mailing_enabled") or 0) == 1
            and (settings.get("smtp_host") or "").strip()
            and (settings.get("smtp_port") or 0)
            and (settings.get("smtp_user") or "").strip()
            and (settings.get("smtp_pass") or "") != ""
            and (settings.get("mail_from") or "").strip()
        )
    except Exception:
        return False

def effective_notifications_order(settings: Dict, user: Dict | None = None) -> List[str]:
    """Return the effective notification order for a given user.

    If settings.user_notifications_can_override == 1 and the user has a non-empty
    vodum_users.notifications_order_override, that value wins. Otherwise, we fall back
    to settings.notifications_order.
    """
    base = parse_notifications_order((settings or {}).get("notifications_order"))
    if not user:
        return base

    try:
        can_override = int((settings or {}).get("user_notifications_can_override") or 0) == 1
    except Exception:
        can_override = False

    if not can_override:
        return base

    override_raw = (user or {}).get("notifications_order_override")
    override = parse_notifications_order(override_raw)
    # If override_raw is empty/None => parse returns ["email"], so we must check raw itself
    if override_raw and str(override_raw).strip():
        return override

    return base
