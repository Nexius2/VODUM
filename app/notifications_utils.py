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
