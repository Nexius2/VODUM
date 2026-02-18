import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from flask import g, current_app

from db_manager import DBManager
from logging_utils import get_logger
from core.i18n import init_i18n, get_translator
from core.backup import BackupConfig


# -----------------------------
# DB helpers (request-scoped)
# -----------------------------
def get_db() -> DBManager:
    if "db" not in g:
        g.db = DBManager(current_app.config["DATABASE"])
    return g.db


def scheduler_db_provider(database_path: str | None = None) -> DBManager:
    """
    Provider DB hors-request.
    - Si database_path est fourni, il est utilisé.
    - Sinon, on tente DATABASE_PATH env puis (en dernier recours) current_app.
    """
    if database_path:
        return DBManager(database_path)
    env_path = os.environ.get("DATABASE_PATH")
    if env_path:
        return DBManager(env_path)
    return DBManager(current_app.config["DATABASE"])


def init_app_i18n(app):
    # kept as wrapper to preserve original init signature usage
    init_i18n(app, get_db)


def close_db(_exception=None):
    g.pop("db", None)


# -----------------------------
# Generic helpers
# -----------------------------
def table_exists(db: DBManager, name: str) -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return row is not None


def add_log(level, category, message, details=None):
    """
    Log applicatif centralisé.
    Écrit UNIQUEMENT dans les logs texte via logging_utils.

    - Aucun accès DB
    - Aucun lock possible
    - Anonymisation gérée par logging_utils
    """
    logger = get_logger(category)

    if details is not None:
        try:
            message = f"{message} | details={details}"
        except Exception:
            message = f"{message} | details=<unserializable>"

    level = str(level).lower()

    if level == "debug":
        logger.debug(message)
    elif level == "info":
        logger.info(message)
    elif level in ("warn", "warning"):
        logger.warning(message)
    elif level == "error":
        logger.error(message)
    elif level == "critical":
        logger.critical(message)
    else:
        logger.info(message)


# -----------------------------
# Email helpers (copied from app.py)
# -----------------------------
def _html_to_plain(html: str) -> str:
    """Fallback texte propre à partir d'un HTML simple."""
    if not html:
        return ""
    txt = re.sub(r"(?i)<br\s*/?>", "\n", html)
    txt = re.sub(r"(?i)</p\s*>", "\n\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _normalize_body_to_html(body: str) -> str:
    """
    Si le template contient du texte brut (sans balises),
    on transforme les retours ligne en <br>.
    Si c'est déjà du HTML, on ne touche pas.
    """
    if not body:
        return ""
    if re.search(r"<[a-zA-Z][^>]*>", body):
        return body

    escaped = (
        body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    return escaped.replace("\n", "<br>\n")


def _wrap_email_html(inner_html: str, title: str = "Stream Empire") -> str:
    """
    Enveloppe 'email-safe' (Gmail/Outlook) : tables + styles inline.
    """
    inner_html = inner_html or ""
    return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background-color:#0b1220;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0b1220;padding:24px 0;">
      <tr>
        <td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;background:#111a2e;border:1px solid rgba(255,255,255,0.08);border-radius:12px;overflow:hidden;">
            <tr>
              <td style="padding:18px 22px;font-family:Arial,Helvetica,sans-serif;font-size:18px;font-weight:bold;color:#ffffff;border-bottom:1px solid rgba(255,255,255,0.08);">
                {title}
              </td>
            </tr>
            <tr>
              <td style="padding:18px 22px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;color:#e5e7eb;">
                {inner_html}
              </td>
            </tr>
            <tr>
              <td style="padding:14px 22px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;color:#9ca3af;border-top:1px solid rgba(255,255,255,0.08);">
                © {title} — Ceci est un email automatique.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_email_via_settings(
    to_email: str,
    subject: str,
    body: str,
    *,
    is_html: bool = False,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
) -> bool:
    """
    Envoie un email en utilisant la configuration stockée en base (table settings).

    ✅ Supporte TEXTE BRUT dans Vodum (auto converti en HTML joli)
    ✅ Envoie multipart/alternative (texte + html)
    ✅ Corrige sqlite3.Row (pas de .get())
    """
    logger = get_logger("mailing")

    if not to_email:
        logger.warning("[MAIL] Destinataire vide, envoi annulé")
        return False

    db = get_db()

    settings_row = db.query_one("SELECT * FROM settings LIMIT 1")
    if not settings_row:
        logger.error("[MAIL] Aucun paramètre mail trouvé en base")
        return False

    settings = dict(settings_row)

    if not settings.get("mailing_enabled"):
        logger.info("[MAIL] Mailing désactivé dans les paramètres")
        return False

    smtp_host = settings.get("smtp_host")
    smtp_port = settings.get("smtp_port") or 587
    smtp_user = settings.get("smtp_user")
    smtp_pass = settings.get("smtp_pass") or ""
    smtp_tls = bool(settings.get("smtp_tls"))
    mail_from = settings.get("mail_from") or smtp_user

    try:
        smtp_port = int(smtp_port)
    except (TypeError, ValueError):
        smtp_port = 587

    if not smtp_host:
        logger.error("[MAIL] Configuration SMTP incomplète (host manquant)")
        return False

    if not mail_from:
        logger.error("[MAIL] Adresse d'expéditeur introuvable")
        return False

    if is_html:
        body_html_inner = body or ""
        body_plain = _html_to_plain(body_html_inner)
    else:
        body_html_inner = _normalize_body_to_html(body or "")
        body_plain = (body or "").strip()

    body_html = _wrap_email_html(body_html_inner, title="Stream Empire")

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    msg.set_content(body_plain, subtype="plain", charset="utf-8")
    msg.add_alternative(body_html, subtype="html", charset="utf-8")

    recipients = [to_email]
    if cc:
        recipients.extend(cc)
    if bcc:
        recipients.extend(bcc)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if smtp_tls:
                server.starttls()

            if smtp_user:
                server.login(smtp_user, smtp_pass)

            server.send_message(msg, from_addr=mail_from, to_addrs=recipients)

        logger.info(f"[MAIL] Email envoyé à {to_email}")
        return True

    except Exception as e:
        logger.error(f"[MAIL] Erreur SMTP vers {to_email}: {e}", exc_info=True)
        return False


# -----------------------------
# Backup helpers (avoid closures)
# -----------------------------
def get_backup_cfg() -> BackupConfig:
    backup_dir = current_app.config.get("BACKUP_DIR") or os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups")
    database_path = current_app.config["DATABASE"]
    return BackupConfig(backup_dir=backup_dir, database_path=database_path)