#!/usr/bin/env python3

"""
send_expiration_emails.py — VERSION CORRIGÉE
-----------------------------------------------
✓ Rendu correct des variables {username}, {days_left}, {expiration_date}
✓ Utilise build_user_context + render_mail (comme l’UI)
✓ Emails secondaires conservés
✓ Anti-doublons fiable
✓ Logging fichier + tasks_engine
"""
from datetime import datetime, date
from tasks_engine import task_logs
from logging_utils import get_logger
from mailing_utils import build_user_context, render_mail
from notifications_utils import normalize_notifications_order, is_email_ready
from discord_utils import is_discord_ready, send_discord_dm, DiscordSendError
from email_sender import send_email
import re
log = get_logger("send_expiration_emails")





# --------------------------------------------------------
# Helper : envoyer un email
# --------------------------------------------------------
def was_sent_recently(db, user_id: int, template_type: str, cooldown_hours: int = 24) -> bool:
    """
    Cooldown robuste:
    - fonctionne si sent_at est stocké en TEXT (YYYY-MM-DD HH:MM:SS)
    - fonctionne si sent_at est stocké en INTEGER (epoch)
    """
    window = f"-{int(cooldown_hours)} hours"

    row = db.query_one(
        """
        SELECT 1
        FROM sent_emails
        WHERE user_id = ?
          AND template_type = ?
          AND (
                -- cas 1: sent_at est un datetime texte
                (typeof(sent_at) != 'integer' AND julianday(sent_at) >= julianday('now', ?))
                OR
                -- cas 2: sent_at est un epoch integer
                (typeof(sent_at) = 'integer' AND sent_at >= CAST(strftime('%s','now', ?) AS INTEGER))
              )
        LIMIT 1
        """,
        (user_id, template_type, window, window),
    )
    return bool(row)




# --------------------------------------------------------
# Tâche principale
# --------------------------------------------------------
def run(task_id: int, db):
    """
    Envoi des emails liés aux expirations d’abonnement
    (préavis, relance, fin)
    """

    task_logs(task_id, "info", "Tâche send_expiration_emails démarrée…")
    log.info("=== SEND EXPIRATION EMAILS : STARTING ===")

    try:
        # --------------------------------------------------------
        # 1) Vérification configuration globale
        # --------------------------------------------------------
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else None

        if not settings or not settings["mailing_enabled"]:
            msg = "Mailing disabled → no action."
            log.warning(msg)
            task_logs(task_id, "info", msg)
            return

        log.debug("Mailing enabled. Loading templates…")

        notifications_order = normalize_notifications_order(settings)

        # Respect the global notification order:
        # - If Email is NOT the primary channel, do nothing here.
        # - Discord task will handle Discord-first (with optional fallback to Email).
        if notifications_order[:1] != ["email"]:
            msg = "Email is not the primary notification channel → no action."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return

        discord_ready = is_discord_ready(settings)


        preavis_days = int(settings["preavis_days"])
        reminder_days = int(settings["reminder_days"])

        log.info(
            f"Mailing delays → preavis={preavis_days}j | reminder={reminder_days}j"
        )


        # --------------------------------------------------------
        # 2) Charger tous les templates
        # --------------------------------------------------------
        templates = {
            row["type"]: row
            for row in db.query("SELECT * FROM email_templates")
        }

        # --------------------------------------------------------
        # 3) Charger les utilisateurs concernés
        # --------------------------------------------------------
        users = db.query(
            """
            SELECT id, username, email, second_email, expiration_date, discord_user_id
            FROM vodum_users u
            WHERE u.expiration_date IS NOT NULL
              AND EXISTS (
                SELECT 1
                FROM media_users mu
                WHERE mu.vodum_user_id = u.id
              )
            """
        )

        today = date.today()
        sent_count = 0

        log.info(f"{len(users)} Users analyzed")
        task_logs(task_id, "info", f"{len(users)} Users analyzed")

        # --------------------------------------------------------
        # 4) Boucle utilisateurs
        # --------------------------------------------------------
        for u in users:
            uid = u["id"]
            username = u["username"]
            email1 = u["email"]
            email2 = u["second_email"]
            exp_raw = u["expiration_date"]

            discord_user_id = (u["discord_user_id"] or "").strip()

            if not email1 and not email2:
                continue

            try:
                exp_date = datetime.fromisoformat(exp_raw).date()
            except Exception:
                log.error(f"[USER] #{uid} Invalid expiration date : {exp_raw}")
                continue

            days_left = (exp_date - today).days
            exp_iso = exp_date.isoformat()


            recipients = []
            if email1:
                recipients.append(email1)
            if email2 and email2 not in recipients:
                recipients.append(email2)

            # ----------------------------------------------------
            # FIN D'ABONNEMENT
            # ----------------------------------------------------
            if exp_date < today:
                tpl = templates.get("fin")
                if tpl:
                    already = db.query_one(
                        """
                        SELECT 1 FROM sent_emails
                        WHERE user_id = ?
                          AND template_type = 'fin'
                          AND expiration_date = ?
                        """,
                        (uid, exp_iso),
                    )

                    # ⛔ STOP spam horaire
                    if already or was_sent_recently(db, uid, "fin", cooldown_hours=24):
                        continue

                    success_any = False
                    for r in recipients:
                        context = build_user_context({
                            "username": username,
                            "email": r,
                            "expiration_date": exp_date.isoformat(),
                            "days_left": days_left,
                        })

                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        ok, _err = send_email(subject, body, r, settings)
                        if ok:
                            success_any = True

                    
                    # Fallback to Discord if configured (order: email -> discord) and email failed
                    if (not success_any) and (notifications_order[:2] == ["email", "discord"]) and discord_ready and discord_user_id:
                        # Avoid duplicates in Discord history
                        already_d = db.query_one(
                            "SELECT 1 FROM sent_discord WHERE user_id=? AND template_type=? AND expiration_date=?",
                            (uid, "fin", exp_iso),
                        )
                        if not already_d:
                            ctx = build_user_context({
                                "username": username,
                                "expiration_date": exp_iso,
                                "days_left": days_left,
                            })
                            # Reuse discord templates for the same type
                            d_tpl = db.query_one("SELECT * FROM discord_templates WHERE type='fin'")
                            if d_tpl:
                                d_title = render_mail(d_tpl["title"] or "", ctx).strip()
                                d_body = render_mail(d_tpl["body"] or "", ctx).strip()
                                d_content = f"**{d_title}**\n{d_body}" if d_title else d_body
                                try:
                                    send_discord_dm(settings.get("discord_bot_token") or "", discord_user_id, d_content)
                                    db.execute(
                                        "INSERT OR IGNORE INTO sent_discord(user_id, template_type, expiration_date, sent_at) VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))",
                                        (uid, "fin", exp_iso),
                                    )
                                    sent_count += 1
                                except DiscordSendError:
                                    pass
                    if success_any:
                        db.execute(
                            """
                            INSERT OR IGNORE INTO sent_emails(
                                user_id,
                                template_type,
                                expiration_date,
                                sent_at
                            )
                            VALUES (?, 'fin', ?, CAST(strftime('%s','now') AS INTEGER))
                            """,
                            (uid, exp_iso),
                        )
                        sent_count += 1
                        log.debug(f"[DB] sent_emails inserted: user={uid} type=fin exp={exp_iso} sent_at=now")




            # ----------------------------------------------------
            # PRÉAVIS / RELANCE
            # ----------------------------------------------------
            for type_ in ("preavis", "relance"):
                tpl = templates.get(type_)
                if not tpl:
                    continue

                if type_ == "preavis":
                    days_before = preavis_days
                else:  # relance
                    days_before = reminder_days

                if days_before <= 0:
                    continue

                if 0 < days_left <= days_before:
                    already = db.query_one(
                        """
                        SELECT 1 FROM sent_emails
                        WHERE user_id=? AND template_type=? AND expiration_date=?
                        """,
                        (uid, type_, exp_iso),
                    )

                    if already or was_sent_recently(db, uid, type_, cooldown_hours=24):
                        continue

                    success_any = False
                    for r in recipients:
                        context = build_user_context({
                            "username": username,
                            "email": r,
                            "expiration_date": exp_date.isoformat(),
                            "days_left": days_left,
                        })

                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        ok, _err = send_email(subject, body, r, settings)
                        if ok:
                            success_any = True

                    
                    # Fallback to Discord if configured (order: email -> discord) and email failed
                    if (not success_any) and (notifications_order[:2] == ["email", "discord"]) and discord_ready and discord_user_id:
                        already_d = db.query_one(
                            "SELECT 1 FROM sent_discord WHERE user_id=? AND template_type=? AND expiration_date=?",
                            (uid, type_, exp_iso),
                        )
                        if not already_d:
                            ctx = build_user_context({
                                "username": username,
                                "expiration_date": exp_iso,
                                "days_left": days_left,
                            })
                            d_tpl = db.query_one("SELECT * FROM discord_templates WHERE type=?", (type_,))
                            if d_tpl:
                                d_title = render_mail(d_tpl["title"] or "", ctx).strip()
                                d_body = render_mail(d_tpl["body"] or "", ctx).strip()
                                d_content = f"**{d_title}**\n{d_body}" if d_title else d_body
                                try:
                                    send_discord_dm(settings.get("discord_bot_token") or "", discord_user_id, d_content)
                                    db.execute(
                                        "INSERT OR IGNORE INTO sent_discord(user_id, template_type, expiration_date, sent_at) VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))",
                                        (uid, type_, exp_iso),
                                    )
                                    sent_count += 1
                                except DiscordSendError:
                                    pass
                    if success_any:
                        db.execute(
                            """
                            INSERT OR IGNORE INTO sent_emails(
                                user_id,
                                template_type,
                                expiration_date,
                                sent_at
                            )
                            VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))
                            """,
                            (uid, type_, exp_iso),
                        )
                        sent_count += 1
                        log.debug(f"[DB] sent_emails inserted: user={uid} type={type_} exp={exp_iso} sent_at=now")

    


        msg = f"send_expiration_emails finished — {sent_count} Email(s) sent"
        log.info(msg)

        if sent_count > 0:
            task_logs(task_id, "success", msg)
        else:
            task_logs(task_id, "info", msg)

    except Exception as e:
        log.error("Error in send_expiration_emails", exc_info=True)
        task_logs(task_id, "error", f"Error send_expiration_emails : {e}")
        raise

    finally:
        log.info("=== SEND EXPIRATION EMAILS : END ===")
