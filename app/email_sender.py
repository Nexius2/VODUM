from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Dict, Tuple

from email_layout_utils import build_email_parts
from secret_store import decrypt_communication_settings


def smtp_auth_method(settings: Dict) -> str:
    method = (settings.get("smtp_auth_method") or "password").strip().lower()
    if method not in ("password", "oauth2"):
        return "password"
    return method


def smtp_oauth2_string(smtp_user: str, access_token: str) -> str:
    return f"user={smtp_user}\x01auth=Bearer {access_token}\x01\x01"


def authenticate_smtp(server: smtplib.SMTP, settings: Dict) -> None:
    smtp_user = (settings.get("smtp_user") or "").strip()
    if not smtp_user:
        return

    if smtp_auth_method(settings) == "oauth2":
        token = (settings.get("smtp_oauth_access_token") or "").strip()
        server.auth("XOAUTH2", lambda _challenge=None: smtp_oauth2_string(smtp_user, token))
        return

    server.login(smtp_user, settings.get("smtp_pass") or "")


def send_email(subject: str, body: str, to_email: str, smtp_settings: Dict, attachments: list[dict] | None = None) -> Tuple[bool, str | None]:
    """Send an email using current SMTP settings.

    Returns (success, error_message).
    """
    smtp_settings = decrypt_communication_settings(smtp_settings)

    if not to_email:
        return False, "Empty recipient email"

    smtp_host = (smtp_settings.get("smtp_host") or "").strip()
    smtp_port = smtp_settings.get("smtp_port") or 587
    smtp_tls  = bool(smtp_settings.get("smtp_tls"))
    smtp_user = (smtp_settings.get("smtp_user") or "").strip()
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

    # Attachments (filesystem paths)
    for att in (attachments or []):
        try:
            filename = (att or {}).get('filename') or 'attachment'
            mime_type = (att or {}).get('mime_type') or 'application/octet-stream'
            path = (att or {}).get('path')
            if not path:
                continue
            maintype, subtype = (mime_type.split('/', 1) + ['octet-stream'])[:2]
            with open(path, 'rb') as f:
                data = f.read()
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
        except Exception:
            # best effort: never fail the whole send just because one attachment is broken
            continue


    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if smtp_tls:
                server.starttls()
            authenticate_smtp(server, smtp_settings)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)
