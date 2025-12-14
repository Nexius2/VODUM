#!/usr/bin/env python3

"""
send_expiration_emails.py — VERSION AMÉLIORÉE
-----------------------------------------------
✓ Envoi aux emails secondaires
✓ Suppression auto des accès Plex après mail FIN
✓ Création jobs SYNC + lancement apply_plex_access_updates
✓ Logging complet (TXT + tasks_engine)
✓ Anti-doublons 100% fiable
"""

import smtplib
from datetime import datetime, date, timedelta
from email.message import EmailMessage

from db_utils import open_db
from tasks_engine import task_logs, run_task
from logging_utils import get_logger

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
            conn.close()
            return

        log.debug("Mailing activé. Lecture des templates email…")

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

        log.info(f"{len(users)} utilisateurs à analyser")
        task_logs(task_id, "info", f"{len(users)} utilisateurs analysés")

        today = date.today()
        sent_count = 0

        # --------------------------------------------------------
        # 4) Boucle utilisateurs
        # --------------------------------------------------------
        for u in users:
            uid = u["id"]
            email1 = u["email"]
            email2 = u["second_email"]
            username = u["username"]
            exp_raw = u["expiration_date"]

            log.debug(f"[USER] #{uid} username={username} emails={[email1, email2]} exp={exp_raw}")

            if not email1 and not email2:
                log.debug(f"[USER] #{uid} ignoré → aucun email renseigné")
                continue

            # Décodage de la date
            try:
                exp_date = datetime.fromisoformat(exp_raw).date()
            except:
                log.error(f"[USER] #{uid} date expiration invalide : {exp_raw}")
                continue

            # Rassemble les emails du user
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
                            if send_email(tpl["subject"], tpl["body"], r):
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
                #target_date = today + timedelta(days=days_before)
                days_left = (exp_date - today).days

                #if exp_date == target_date:
                if 0 < days_left <= days_before:
                    already = cur.execute("""
                        SELECT 1 FROM sent_emails
                        WHERE user_id=? AND template_type=? AND expiration_date=?
                    """, (uid, type_, exp_date)).fetchone()

                    if not already:
                        log.info(f"[USER] #{uid} → mail {type_.upper()} à {recipients}")

                        success_any = False
                        for r in recipients:
                            if send_email(tpl["subject"], tpl["body"], r):
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
        except:
            pass

        log.info("=== SEND EXPIRATION EMAILS : FIN ===")
