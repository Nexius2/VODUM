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
from tasks_engine import task_logs
from notifications_utils import is_email_ready
from discord_utils import enrich_discord_settings, is_discord_ready

from communications_engine import send_to_user, record_history, fetch_template_attachments, SendAttempt
from email_sender import send_email
from mailing_utils import build_user_context, render_mail

log = get_logger("send_expiration_emails")

def _flush_comm_scheduled(db, settings: dict, task_id: int | None):
    """
    Flush comm_scheduled queue.

    Rules:
    - If trigger_event == 'user_creation' => EMAIL ONLY (no Discord).
    - Otherwise => unified engine (email+discord depending on config).
    """
    rows = db.query(
        """
        SELECT
          q.id AS scheduled_id,
          q.template_id,
          q.vodum_user_id,
          q.provider,
          q.server_id,
          q.send_at,
          q.status,
          t.key AS template_key,
          t.subject,
          t.body,
          t.trigger_event
        FROM comm_scheduled q
        JOIN comm_templates t ON t.id = q.template_id
        WHERE q.status = 'pending'
          AND datetime(q.send_at) <= datetime('now')
          AND t.enabled = 1
        ORDER BY q.send_at ASC, q.id ASC
        LIMIT 200
        """
    )
    due = [dict(r) for r in (rows or [])]
    if not due:
        return 0, 0

    sent = 0
    failed = 0

    for q in due:
        scheduled_id = int(q["scheduled_id"])
        tpl_id = int(q["template_id"])
        uid = int(q["vodum_user_id"])
        trigger_event = (q.get("trigger_event") or "expiration").lower()

        user = db.query_one(
            """
            SELECT id, username, firstname, lastname, email, second_email, expiration_date, discord_user_id, notifications_order_override
            FROM vodum_users
            WHERE id = ?
            """,
            (uid,),
        )
        user = dict(user) if user else None
        if not user:
            db.execute(
                "UPDATE comm_scheduled SET status='error', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                ("User not found", scheduled_id),
            )
            failed += 1
            continue

        exp_iso = (user.get("expiration_date") or "")[:10]
        subject, body = _format_message(q.get("subject") or "", q.get("body") or "", user, exp_iso)
        attachments = fetch_template_attachments(db, tpl_id)

        # ---- USER CREATION: EMAIL ONLY ----
        if trigger_event == "user_creation":
            to_email = (user.get("email") or "").strip() or (user.get("second_email") or "").strip()
            ok = False
            err = None
            if not to_email:
                ok = False
                err = "No user email"
            else:
                ok, err = send_email(subject, body, to_email, settings, attachments=attachments)

            attempt = SendAttempt(channel="email", status="sent" if ok else "failed", error=err)

            record_history(
                db=db,
                kind="template",
                template_id=tpl_id,
                campaign_id=None,
                user_id=uid,
                attempt=attempt,
                meta={
                    "template_key": q.get("template_key"),
                    "trigger_event": "user_creation",
                    "provider": q.get("provider"),
                    "server_id": q.get("server_id"),
                    "scheduled_id": scheduled_id,
                    "send_at": q.get("send_at"),
                    "attachments": [a.get("filename") for a in (attachments or [])],
                },
            )

            if ok:
                db.execute("UPDATE comm_scheduled SET status='sent', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (scheduled_id,))
                sent += 1
            else:
                db.execute("UPDATE comm_scheduled SET status='error', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (err or "Email failed", scheduled_id))
                failed += 1

            continue  # IMPORTANT: never send Discord for user_creation

        # ---- OTHER EVENTS (expiration): unified engine (email+discord) ----
        attempts = send_to_user(
            db=db,
            settings=settings,
            user=user,
            subject=subject,
            body=body,
            attachments=attachments,
        )
        any_ok = any(a.status == "sent" for a in attempts)

        for att in attempts:
            record_history(
                db=db,
                kind="template",
                template_id=tpl_id,
                campaign_id=None,
                user_id=uid,
                attempt=att,
                meta={
                    "template_key": q.get("template_key"),
                    "trigger_event": trigger_event,
                    "provider": q.get("provider"),
                    "server_id": q.get("server_id"),
                    "scheduled_id": scheduled_id,
                    "send_at": q.get("send_at"),
                    "attachments": [a.get("filename") for a in (attachments or [])],
                },
            )

        if any_ok:
            db.execute("UPDATE comm_scheduled SET status='sent', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (scheduled_id,))
            sent += 1
        else:
            err = "; ".join([a.error for a in attempts if a.error])[:1000] if attempts else "No channel available"
            db.execute("UPDATE comm_scheduled SET status='error', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (err, scheduled_id))
            failed += 1

    if task_id is not None:
        task_logs(task_id, "info", f"comm_scheduled flushed: sent={sent} failed={failed}")

    return sent, failed


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

def _already_sent_any(db, user_id: int, template_key: str, exp_iso: str) -> bool:
    # If either email OR discord already sent for this template/date, skip retrying.
    return _already_sent_email(db, user_id, template_key, exp_iso) or _already_sent_discord(db, user_id, template_key, exp_iso)

def _format_message(subject: str, body: str, user: dict, exp_iso: str) -> tuple[str, str]:
    ctx_input = dict(user or {})
    ctx_input["expiration_date"] = exp_iso

    context = build_user_context(ctx_input)

    msg_subject = render_mail(subject or "", context)
    msg_body = render_mail(body or "", context)
    return msg_subject, msg_body


def run(task_id: int | None = None, db=None):
    if db is None:
        db = get_db()

    try:
        task_logs(task_id, "info", "Task send_expiration_emails (unified) started")

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        
        # If no channel is ready, do nothing (avoid pointless DB work and errors)
        s2 = enrich_discord_settings(db, settings)
        email_ok = is_email_ready(settings)
        discord_ok = is_discord_ready(s2)

        if not email_ok and not discord_ok:
            msg = "Mailing + Discord disabled or not configured → no action."
            task_logs(task_id, "info", msg)
            log.warning(msg)
            return
        
        # Flush scheduled notifications (user_creation days_after etc.)
        _flush_comm_scheduled(db, settings, task_id)

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
            SELECT id, username, firstname, lastname, email, second_email, expiration_date, discord_user_id, notifications_order_override
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

            # Choose which template applies (supports BEFORE and AFTER for expiration)
            tpl_key = None

            def _get_after(tpl: dict | None) -> int | None:
                if not tpl:
                    return None
                v = tpl.get("days_after")
                if v is None:
                    return None
                try:
                    return int(v)
                except Exception:
                    return None

            # preavis / relance / fin can be:
            # - days_before => send when days_left == +N
            # - days_after  => send when days_left == -N  (N days after expiration)
            preavis_tpl = templates.get("preavis")
            relance_tpl = templates.get("relance")
            fin_tpl = templates.get("fin")

            preavis_before = _get_days_before(preavis_tpl, None)
            relance_before = _get_days_before(relance_tpl, None)
            fin_before = _get_days_before(fin_tpl, None)

            preavis_after = _get_after(preavis_tpl)
            relance_after = _get_after(relance_tpl)
            fin_after = _get_after(fin_tpl)

            # BEFORE checks
            if preavis_before is not None and days_left == int(preavis_before):
                tpl_key = "preavis"
            elif relance_before is not None and days_left == int(relance_before):
                tpl_key = "relance"
            elif fin_before is not None and days_left == int(fin_before):
                tpl_key = "fin"

            # AFTER checks (days_left becomes negative after expiration)
            elif preavis_after is not None and days_left == -int(preavis_after):
                tpl_key = "preavis"
            elif relance_after is not None and days_left == -int(relance_after):
                tpl_key = "relance"
            elif fin_after is not None and days_left == -int(fin_after):
                tpl_key = "fin"

            # Fallback (legacy behavior) if fin has no before/after configured:
            elif (fin_before is None and fin_after is None) and days_left < 0:
                tpl_key = "fin"

            if not tpl_key:
                continue

            tpl = templates.get(tpl_key)
            if not tpl or int(tpl.get("enabled") or 0) != 1:
                continue

            # Avoid retrying the same template again and again on every run
            if _already_sent_any(db, uid, tpl_key, exp_iso):
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
