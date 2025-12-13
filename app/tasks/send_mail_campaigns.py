#!/usr/bin/env python3

"""
send_mail_campaigns.py — VERSION TXT LOGGING (PRO)
--------------------------------------------------
✓ Tous les logs → fichiers TXT (/logs/app.log)
✓ ZERO log en DB sauf task_logs()
✓ Très verbeux : DEBUG, INFO, WARNING, ERROR
✓ Connexion DB locale, jamais celle du scheduler
✓ Envoi SMTP robuste et logué
"""

import smtplib
from email.mime.text import MIMEText

from db_utils import open_db
from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("send_mail_campaigns")


# --------------------------------------------------------
# Helper : envoyer un email
# --------------------------------------------------------
def send_email(settings, to_email, subject, body):
    if not to_email:
        raise ValueError("Email vide")

    log.debug(
        f"[SMTP] Envoi email → to={to_email}, subject={subject}, "
        f"host={settings['smtp_host']}:{settings['smtp_port']}, tls={settings['smtp_tls']}"
    )

    msg = MIMEText(body)
    msg["From"] = settings["mail_from"] or settings["smtp_user"]
    msg["To"] = to_email
    msg["Subject"] = subject

    try:
        server = smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=20)

        if settings["smtp_tls"]:
            log.debug("[SMTP] STARTTLS…")
            server.starttls()

        if settings["smtp_user"]:
            log.debug("[SMTP] Authentification SMTP…")
            server.login(settings["smtp_user"], settings["smtp_pass"])

        server.send_message(msg)
        server.quit()

        log.info(f"[SMTP] Email envoyé → {to_email}")
        return True

    except Exception as e:
        log.error(f"[SMTP] Erreur d'envoi vers {to_email}: {e}", exc_info=True)
        return False



# --------------------------------------------------------
# Task principale
# --------------------------------------------------------
def run(task_id=None, db=None):
    task_logs(task_id, "info", "Tâche send_mail_campaigns démarrée")
    log.info("=== SEND MAIL CAMPAIGNS : DÉMARRAGE ===")

    # Toujours utiliser une DB locale
    conn = open_db()
    conn.row_factory = __import__("sqlite3").Row
    cur = conn.cursor()

    try:
        # --------------------------------------------------------
        # Charger settings SMTP
        # --------------------------------------------------------
        settings = cur.execute("SELECT * FROM settings WHERE id = 1").fetchone()

        if not settings or not settings["mailing_enabled"]:
            msg = "Mailing désactivé → aucune action."
            log.warning(msg)
            task_logs(task_id, "info", msg)
            return

        log.debug("Mailing activé. Lecture des campagnes en attente…")

        # --------------------------------------------------------
        # Campagnes en attente
        # --------------------------------------------------------
        campaigns = cur.execute("""
            SELECT * FROM mail_campaigns
            WHERE status='pending'
            ORDER BY created_at ASC
        """).fetchall()

        if not campaigns:
            msg = "Aucune campagne en attente."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return

        log.info(f"{len(campaigns)} campagne(s) trouvée(s).")

        # --------------------------------------------------------
        # Traiter chaque campagne
        # --------------------------------------------------------
        for camp in campaigns:
            camp_id = camp["id"]
            subject = camp["subject"]
            body = camp["body"]
            server_id = camp["server_id"]
            is_test = camp["is_test"]

            log.info(f"--- Campagne #{camp_id} ---")
            log.debug(f"sujet={subject}, server_id={server_id}, test={is_test}")

            task_logs(task_id, "info", f"Traitement campagne #{camp_id}")

            # Passer la campagne en "sending"
            cur.execute("UPDATE mail_campaigns SET status='sending' WHERE id=?", (camp_id,))
            conn.commit()

            # --------------------------------------------------------
            # Destinataires
            # --------------------------------------------------------
            if is_test:
                recipients = [{"id": 0, "email": settings["admin_email"], "username": "ADMIN"}]
                log.info(f"Mode test → destinataire unique : {settings['admin_email']}")
            else:
                if server_id == 0:
                    cur.execute("SELECT id, email, username FROM users WHERE email IS NOT NULL")
                else:
                    cur.execute("""
                        SELECT u.id, u.email, u.username
                        FROM users u
                        JOIN user_servers us ON us.user_id=u.id
                        WHERE us.server_id=? AND u.email IS NOT NULL
                    """, (server_id,))
                recipients = cur.fetchall()

                log.info(f"{len(recipients)} destinataire(s) sélectionné(s)")

            sent_count = 0
            error_count = 0

            # --------------------------------------------------------
            # Boucle envoi mails
            # --------------------------------------------------------
            for user in recipients:
                uid = user["id"]
                email = user["email"]
                username = user["username"]

                log.debug(f"[USER] #{uid} email={email} username={username}")

                # Substitutions du corps
                final_body = (
                    body.replace("{username}", username or "")
                        .replace("{email}", email or "")
                )

                # Log body final en DEBUG (optionnel)
                log.debug(f"[MAIL] Corps final pour {email}:\n{final_body}")

                ok = send_email(settings, email, subject, final_body)

                if ok:
                    sent_count += 1
                else:
                    error_count += 1

            # --------------------------------------------------------
            # Campagne terminée
            # --------------------------------------------------------
            cur.execute("""
                UPDATE mail_campaigns
                SET status='finished', finished_at=datetime('now')
                WHERE id=?
            """, (camp_id,))
            conn.commit()

            log.info(
                f"Campagne {camp_id} terminée → envoyés={sent_count}, erreurs={error_count}"
            )
            task_logs(task_id, "info", f"Campagne {camp_id} OK={sent_count}, ERR={error_count}")

        # --------------------------------------------------------
        # Fin
        # --------------------------------------------------------
        task_logs(task_id, "success", "Toutes les campagnes pending traitées.")
        log.info("=== SEND MAIL CAMPAIGNS : TERMINÉ ===")

    except Exception as e:
        log.error(f"Erreur générale dans send_mail_campaigns : {e}", exc_info=True)
        task_logs(task_id, "error", f"Erreur send_mail_campaigns : {e}")

    finally:
        try:
            conn.close()
        except:
            pass
