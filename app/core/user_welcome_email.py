import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Optional

from email_layout_utils import build_email_parts
from email_sender import authenticate_smtp
from secret_store import decrypt_communication_settings


def send_email_via_settings(settings: Dict[str, Any], to_email: str, subject: str, body: str) -> bool:
    settings = decrypt_communication_settings(settings)
    smtp_host = settings.get("smtp_host")
    smtp_port = settings.get("smtp_port") or 587
    smtp_tls = bool(settings.get("smtp_tls"))
    smtp_user = settings.get("smtp_user")
    mail_from = settings.get("mail_from") or smtp_user
    if not smtp_host or not mail_from or not to_email:
        return False
    try:
        smtp_port = int(smtp_port)
    except Exception:
        smtp_port = 587

    plain, full_html = build_email_parts(body, settings)
    message = EmailMessage()
    message["From"] = mail_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(plain, subtype="plain", charset="utf-8")
    message.add_alternative(full_html, subtype="html", charset="utf-8")
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        if smtp_tls:
            server.starttls()
        authenticate_smtp(server, settings)
        server.send_message(message)
    return True


def get_welcome_template(db, provider: str, server_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one(
        """
        SELECT id, provider, server_id, subject, body, created_at, updated_at
        FROM welcome_email_templates
        WHERE provider = ? AND server_id = ?
        LIMIT 1
        """,
        (provider, server_id),
    )
    if row:
        return dict(row)
    row = db.query_one(
        """
        SELECT id, provider, server_id, subject, body, created_at, updated_at
        FROM welcome_email_templates
        WHERE provider = ? AND server_id IS NULL
        LIMIT 1
        """,
        (provider,),
    )
    return dict(row) if row else None
