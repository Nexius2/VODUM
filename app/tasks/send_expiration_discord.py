#!/usr/bin/env python3

from datetime import datetime, date

from tasks_engine import task_logs
from logging_utils import get_logger
from mailing_utils import build_user_context, render_mail
from discord_utils import is_discord_ready, enrich_discord_settings, send_discord_dm, DiscordSendError
from notifications_utils import normalize_notifications_order, effective_notifications_order, is_email_ready
from email_sender import send_email


log = get_logger("send_expiration_discord")


def was_sent_recently(db, user_id: int, template_type: str, cooldown_hours: int = 24) -> bool:
    window = f"-{int(cooldown_hours)} hours"
    row = db.query_one(
        """
        SELECT 1
        FROM sent_discord
        WHERE user_id = ?
          AND template_type = ?
          AND sent_at >= CAST(strftime('%s','now', ?) AS INTEGER)
        LIMIT 1
        """,
        (user_id, template_type, window),
    )
    return bool(row)


def run(task_id: int, db):
    task_logs(task_id, "info", "Task send_expiration_discord started")
    log.info("=== SEND EXPIRATION DISCORD : START ===")

    try:
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        settings = enrich_discord_settings(db, settings)

        notifications_order = normalize_notifications_order(settings)




        if not is_discord_ready(settings):
            msg = "Discord disabled or not configured → no action."
            task_logs(task_id, "info", msg)
            log.warning(msg)
            return

        preavis_days = int(settings.get("preavis_days") or 30)
        reminder_days = int(settings.get("reminder_days") or 7)

        templates = {row["type"]: row for row in db.query("SELECT * FROM discord_templates")}

        users = db.query(
            """
            SELECT id, username, email, second_email, discord_user_id, expiration_date, notifications_order_override
            FROM vodum_users u
            WHERE u.expiration_date IS NOT NULL
              AND COALESCE(u.discord_user_id,'') <> ''
              AND EXISTS (
                SELECT 1
                FROM media_users mu
                WHERE mu.vodum_user_id = u.id
              )
            """
        )

        today = date.today()
        sent_count = 0

        for u in users:
            u_dict = dict(u) if not isinstance(u, dict) else u
            eff_order = effective_notifications_order(settings, u_dict)
            if eff_order[:1] != ["discord"]:
                continue

            uid = u["id"]
            username = u["username"]
            discord_user_id = (u["discord_user_id"] or "").strip()
            email1 = (u.get('email') or '').strip()
            email2 = (u.get('second_email') or '').strip()
            exp_raw = u["expiration_date"]

            if not discord_user_id:
                continue

            try:
                exp_date = datetime.fromisoformat(exp_raw).date()
            except Exception:
                log.error(f"[USER] #{uid} Invalid expiration date : {exp_raw}")
                continue

            days_left = (exp_date - today).days
            exp_iso = exp_date.isoformat()

            def send_tpl(tpl_type: str):
                nonlocal sent_count
                tpl = templates.get(tpl_type)
                if not tpl:
                    return

                already = db.query_one(
                    """
                    SELECT 1 FROM sent_discord
                    WHERE user_id=? AND template_type=? AND expiration_date=?
                    """,
                    (uid, tpl_type, exp_iso),
                )

                if already or was_sent_recently(db, uid, tpl_type, cooldown_hours=24):
                    return

                ctx = build_user_context(
                    {
                        "username": username,
                        "expiration_date": exp_iso,
                        "days_left": days_left,
                    }
                )

                title = render_mail(tpl.get("title") or "", ctx).strip()
                body = render_mail(tpl.get("body") or "", ctx).strip()
                content = f"**{title}**\n{body}" if title else body

                try:
                    send_discord_dm(settings.get('discord_bot_token_effective') or '', discord_user_id, content)
                    db.execute(
                        """
                        INSERT OR IGNORE INTO sent_discord(user_id, template_type, expiration_date, sent_at)
                        VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))
                        """,
                        (uid, tpl_type, exp_iso),
                    )
                    sent_count += 1
                except DiscordSendError as e:
                    log.error(f"[DISCORD] send failed user={uid}: {e}")

                    # Fallback to Email if configured (order: discord -> email)
                    if (eff_order[:2] == ["discord", "email"]) and is_email_ready(settings):
                        recipients = []
                        if email1:
                            recipients.append(email1)
                        if email2 and email2 not in recipients:
                            recipients.append(email2)

                        if recipients:
                            e_tpl = db.query_one("SELECT * FROM email_templates WHERE type=?", (tpl_type,))
                            if e_tpl:
                                sent_ok = False
                                for rcp in recipients:
                                    e_ctx = build_user_context({
                                        "username": username,
                                        "email": rcp,
                                        "expiration_date": exp_iso,
                                        "days_left": days_left,
                                    })
                                    e_subject = render_mail(e_tpl["subject"], e_ctx)
                                    e_body = render_mail(e_tpl["body"], e_ctx)
                                    ok, _err = send_email(e_subject, e_body, rcp, settings)
                                    if ok:
                                        sent_ok = True
                                if sent_ok:
                                    db.execute(
                                        "INSERT OR IGNORE INTO sent_emails(user_id, template_type, expiration_date, sent_at) VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))",
                                        (uid, tpl_type, exp_iso),
                                    )


            # expired
            if exp_date < today:
                send_tpl("fin")
            else:
                if preavis_days > 0 and 0 < days_left <= preavis_days:
                    send_tpl("preavis")
                if reminder_days > 0 and 0 < days_left <= reminder_days:
                    send_tpl("relance")

        msg = f"send_expiration_discord finished — {sent_count} message(s) sent"
        task_logs(task_id, "success" if sent_count else "info", msg)
        log.info(msg)

    except Exception as e:
        log.error("Error in send_expiration_discord", exc_info=True)
        task_logs(task_id, "error", f"Error send_expiration_discord : {e}")
        raise
    finally:
        log.info("=== SEND EXPIRATION DISCORD : END ===")
