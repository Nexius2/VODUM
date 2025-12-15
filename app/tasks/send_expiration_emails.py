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

import smtplib
from datetime import datetime, date, timedelta
from email.message import EmailMessage

from db_utils import open_db
from tasks_engine import task_logs
from logging_utils import get_logger
from mailing_utils import build_user_context, render_mail

log = get_logger("send_expiration_emails")


# --------------------------------------------------------
# Helper : envoyer un email
# --------------------------------------------------------
def send_email(subject, body, to_email):
    if not to_email:
        raise ValueError("Adresse email vide")

    conn = open_db()
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()

    smtp_host = settings["smtp_host"]
    smtp_port = settings["smtp_port"] or 587
    smtp_tls  = bool(settings["smtp_tls"])
    smtp_user = settings["smtp_user"]
    smtp_pass = settings["smtp_pass"]
    mail_from = settings["mail_from"] or smtp_user

    log.debug(
        f"[SMTP] Envoi email → to={to_email}, "
        f"host={smtp_host}:{smtp_port}, tls={smtp_tls}, user={smtp_user}"
    )

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if smtp_tls:
                log.debug("[SMTP] STARTTLS…")
                server.starttls()

            if smtp_user:
                log.debug("[SMTP] Authentification SMTP…")
                server.login(smtp_user, smtp_pass or "")

            server.send_message(msg)

        log.info(f"[SMTP] Email envoyé → {to_email}")
        return True

    except Exception as e:
        log.error(f"[SMTP] Erreur lors de l'envoi à {to_email}: {e}", exc_info=True)
        return False


# --------------------------------------------------------
# Tâche principale
# --------------------------------------------------------
def run(task_id=None, db=None):
    task_logs(task_id, "info", "Tâche send_expiration_emails démarrée…")
    log.info("=== SEND EXPIRATION EMAILS : DÉMARRAGE ===")

    conn = open_db()
    cur = conn.cursor()

    try:
        # --------------------------------------------------------
        # 1) Vérification configuration globale
        # --------------------------------------------------------
        settings = cur.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if not settings or not settings["mailing_enabled"]:
            msg = "Mailing désactivé → aucune action."
            log.warning(msg)
            task_logs(task_id, "info", msg)
            return

        log.debug("Mailing activé. Chargement des templates…")

        # --------------------------------------------------------
        # 2) Charger tous les templates
        # --------------------------------------------------------
        templates = {
            row["type"]: row
            for row in cur.execute("SELECT * FROM email_templates")
        }

        # --------------------------------------------------------
        # 3) Charger les utilisateurs concernés
        # --------------------------------------------------------
        users = cur.execute("""
            SELECT id, username, email, second_email, expiration_date
            FROM users
            WHERE expiration_date IS NOT NULL
        """).fetchall()

        today = date.today()
        sent_count = 0

        log.info(f"{len(users)} utilisateurs analysés")
        task_logs(task_id, "info", f"{len(users)} utilisateurs analysés")

        # --------------------------------------------------------
        # 4) Boucle utilisateurs
        # --------------------------------------------------------
        for u in users:
            uid = u["id"]
            username = u["username"]
            email1 = u["email"]
            email2 = u["second_email"]
            exp_raw = u["expiration_date"]

            log.debug(
                f"[USER] #{uid} username={username} "
                f"emails={[email1, email2]} exp={exp_raw}"
            )

            if not email1 and not email2:
                log.debug(f"[USER] #{uid} ignoré → aucun email")
                continue

            # Parsing date expiration
            try:
                exp_date = datetime.fromisoformat(exp_raw).date()
            except Exception:
                log.error(f"[USER] #{uid} date expiration invalide : {exp_raw}")
                continue

            days_left = (exp_date - today).days

            # Emails destinataires
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
                    already = cur.execute("""
                        SELECT 1 FROM sent_emails
                        WHERE user_id=? AND template_type='fin' AND expiration_date=?
                    """, (uid, exp_date)).fetchone()

                    if not already:
                        log.info(f"[USER] #{uid} → mail FIN à {recipients}")

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

                            if send_email(subject, body, r):
                                success_any = True

                        if success_any:
                            cur.execute("""
                                INSERT INTO sent_emails(user_id, template_type, expiration_date)
                                VALUES (?, 'fin', ?)
                            """, (uid, exp_date))
                            sent_count += 1
                        else:
                            log.error(f"[USER] #{uid} → échec ENVOI FIN")

            # ----------------------------------------------------
            # PRÉAVIS / RELANCE
            # ----------------------------------------------------
            for type_ in ("preavis", "relance"):
                tpl = templates.get(type_)
                if not tpl:
                    continue

                days_before = tpl["days_before"]

                if 0 < days_left <= days_before:
                    already = cur.execute("""
                        SELECT 1 FROM sent_emails
                        WHERE user_id=? AND template_type=? AND expiration_date=?
                    """, (uid, type_, exp_date)).fetchone()

                    if not already:
                        log.info(f"[USER] #{uid} → mail {type_.upper()} à {recipients}")

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

                            if send_email(subject, body, r):
                                success_any = True

                        if success_any:
                            cur.execute("""
                                INSERT INTO sent_emails(user_id, template_type, expiration_date)
                                VALUES (?, ?, ?)
                            """, (uid, type_, exp_date))
                            sent_count += 1
                        else:
                            log.error(f"[USER] #{uid} → échec ENVOI {type_}")

        # --------------------------------------------------------
        # 5) Commit final
        # --------------------------------------------------------
        conn.commit()

        msg = f"send_expiration_emails terminé — {sent_count} email(s) envoyé(s)"
        log.info(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        log.error(f"Erreur dans send_expiration_emails : {e}", exc_info=True)
        task_logs(task_id, "error", f"Erreur lors du traitement : {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

        log.info("=== SEND EXPIRATION EMAILS : FIN ===")
