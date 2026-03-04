"""send_expiration_emails.py — unified communications

This task keeps the historical name for backward compatibility, but it now uses
Unified Communications:
- comm_templates (preavis / relance / fin)
- comm_history (real delivery history, channel used)

Legacy tables (sent_emails / sent_discord) are still updated to avoid duplicate
notifications across restarts and to keep older dashboards stable.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from logging_utils import get_logger
from web.helpers import get_db
from task_logs import task_logs

from communications_engine import send_to_user, record_history, fetch_template_attachments

log = get_logger("send_expiration_emails")


def _parse_date_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _get_template_map(db):
    rows = db.query("SELECT * FROM comm_templates WHERE key IN ('preavis','relance','fin')")
    m = {}
    for r in rows or []:
        m[r["key"]] = dict(r)
    return m


def _get_days_before(template_row: dict | None, fallback: int | None) -> int | None:
    if not template_row:
        return fallback
    v = template_row.get("days_before")
    if v is None:
        return fallback
    try:
        return int(v)
    except Exception:
        return fallback


def _already_sent_email(db, user_id: int, template_key: str, exp_iso: str) -> bool:
    r = db.query_one(
        "SELECT 1 FROM sent_emails WHERE user_id=? AND template_type=? AND expiration_date=?",
        (user_id, template_key, exp_iso),
    )
    return bool(r)


def _already_sent_discord(db, user_id: int, template_key: str, exp_iso: str) -> bool:
    r = db.query_one(
        "SELECT 1 FROM sent_discord WHERE user_id=? AND template_type=? AND expiration_date=?",
        (user_id, template_key, exp_iso),
    )
    return bool(r)


def _format_message(subject: str, body: str, user: dict, exp_iso: str) -> tuple[str, str]:
    username = user.get("username") or ""
    email = user.get("email") or ""
    msg_subject = (subject or "").replace("{username}", username).replace("{email}", email).replace("{expiration_date}", exp_iso)
    msg_body = (body or "").replace("{username}", username).replace("{email}", email).replace("{expiration_date}", exp_iso)
    return msg_subject, msg_body


def run(task_id: int | None = None):
    db = get_db()

    try:
        task_logs(task_id, "info", "Task send_expiration_emails (unified) started")

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        # Templates (unified)
        templates = _get_template_map(db)

        # Backward-compat: legacy global delays can still be used as fallback
        try:
            legacy_preavis = int(settings.get("preavis_days") or 0)
        except Exception:
            legacy_preavis = 0
        try:
            legacy_relance = int(settings.get("reminder_days") or 0)
        except Exception:
            legacy_relance = 0

        preavis_days = _get_days_before(templates.get("preavis"), legacy_preavis) or None
        relance_days = _get_days_before(templates.get("relance"), legacy_relance) or None

        log.info(f"Unified delays → preavis={preavis_days} | relance={relance_days}")

        # Users concerned
        users = db.query(
            """
            SELECT id, username, email, second_email, expiration_date, discord_user_id, notifications_order_override
            FROM vodum_users u
            WHERE u.expiration_date IS NOT NULL
              AND EXISTS (SELECT 1 FROM media_users mu WHERE mu.vodum_user_id = u.id)
            """
        )

        today = date.today()
        sent_users_ok = 0
        sent_users_failed = 0

        task_logs(task_id, "info", f"{len(users)} Users analyzed")

        for u in users or []:
            u = dict(u)
            uid = int(u["id"])
            exp = _parse_date_iso(u.get("expiration_date"))
            if not exp:
                continue

            exp_iso = exp.isoformat()
            days_left = (exp - today).days

            # Choose which template applies
            tpl_key = None
            if days_left < 0:
                tpl_key = "fin"
            else:
                if preavis_days is not None and days_left == int(preavis_days):
                    tpl_key = "preavis"
                elif relance_days is not None and days_left == int(relance_days):
                    tpl_key = "relance"

            if not tpl_key:
                continue

            tpl = templates.get(tpl_key)
            if not tpl or int(tpl.get("enabled") or 0) != 1:
                continue

            subject, body = _format_message(tpl.get("subject") or "", tpl.get("body") or "", u, exp_iso)
            attachments = fetch_template_attachments(db, int(tpl["id"]))

            # Run unified engine. It will decide which channel(s) to use.
            attempts = send_to_user(
                db=db,
                settings=settings,
                user=u,
                subject=subject,
                body=body,
                attachments=attachments,
            )

            any_sent = any(a.status == "sent" for a in attempts)

            # Save unified history + legacy sent_* anti-dup markers
            for att in attempts:
                meta = {
                    "template_key": tpl_key,
                    "expiration_date": exp_iso,
                    "days_left": days_left,
                    "template_id": tpl.get("id"),
                    "attachments": [a.get("filename") for a in (attachments or [])],
                }
                record_history(
                    db=db,
                    kind="template",
                    template_id=int(tpl.get("id")),
                    campaign_id=None,
                    user_id=uid,
                    attempt=att,
                    meta=meta,
                )

                # Only mark legacy tables when the channel actually succeeded.
                if att.status == "sent":
                    if att.channel == "email" and not _already_sent_email(db, uid, tpl_key, exp_iso):
                        db.execute(
                            """
                            INSERT OR IGNORE INTO sent_emails(user_id, template_type, expiration_date, sent_at)
                            VALUES (?, ?, ?, datetime('now'))
                            """,
                            (uid, tpl_key, exp_iso),
                        )
                    if att.channel == "discord" and not _already_sent_discord(db, uid, tpl_key, exp_iso):
                        db.execute(
                            """
                            INSERT OR IGNORE INTO sent_discord(user_id, template_type, expiration_date, sent_at)
                            VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))
                            """,
                            (uid, tpl_key, exp_iso),
                        )

            if any_sent:
                sent_users_ok += 1
            else:
                sent_users_failed += 1

        msg = f"send_expiration_emails finished — ok={sent_users_ok} failed={sent_users_failed}"
        log.info(msg)
        task_logs(task_id, "info", msg)

    except Exception as e:
        log.error("Error in send_expiration_emails", exc_info=True)
        task_logs(task_id, "error", f"Error send_expiration_emails : {e}")
        raise
