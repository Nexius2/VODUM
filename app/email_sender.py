from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Dict, Tuple

from email_layout_utils import build_email_parts


def send_email(subject: str, body: str, to_email: str, smtp_settings: Dict) -> Tuple[bool, str | None]:
    """Send an email using current SMTP settings.

    Returns (success, error_message).
    """
    if not to_email:
        return False, "Empty recipient email"

    smtp_host = (smtp_settings.get("smtp_host") or "").strip()
    smtp_port = smtp_settings.get("smtp_port") or 587
    smtp_tls  = bool(smtp_settings.get("smtp_tls"))
    smtp_user = (smtp_settings.get("smtp_user") or "").strip()
    smtp_pass = smtp_settings.get("smtp_pass") or ""
    mail_from = (smtp_settings.get("mail_from") or smtp_user).strip()

    try:
        smtp_port = int(smtp_port)
    except (TypeError, ValueError):
        smtp_port = 587

    plain, full_html = build_email_parts(body, smtp_settings)

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.set_content(plain, subtype="plain", charset="utf-8")
    msg.add_alternative(full_html, subtype="html", charset="utf-8")

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if smtp_tls:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)
