#!/usr/bin/env python3

"""
send_mail_campaigns.py — VERSION DBMANAGER
--------------------------------------------------
✓ Utilise DBManager (connexion unique, sérialisée)
✓ ZÉRO ouverture / fermeture DB dans la tâche
✓ ZÉRO commit manuel
✓ finally propre (log uniquement)
✓ Flux linéaire type Radarr
✓ SMTP robuste
✓ Rendu via build_user_context + render_mail
"""

import smtplib
from email.mime.text import MIMEText
from datetime import datetime, date

from tasks_engine import task_logs
from logging_utils import get_logger
from mailing_utils import build_user_context, render_mail

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
        with smtplib.SMTP(
            settings["smtp_host"],
            settings["smtp_port"],
            timeout=30
        ) as server:

            if settings["smtp_tls"]:
                server.starttls()

            if settings["smtp_user"]:
                server.login(settings["smtp_user"], settings["smtp_pass"])

            server.send_message(msg)

        log.info(f"[SMTP] Email envoyé → {to_email}")
        return True

    except Exception as e:
        log.error(f"[SMTP] Échec envoi → {to_email} : {e}")
        return False



# --------------------------------------------------------
# Tâche principale
# --------------------------------------------------------
def run(task_id: int, db):
    """
    Envoi des campagnes d'email programmées
    """

    task_logs(task_id, "info", "Tâche send_mail_campaigns démarrée")
    log.info("=== SEND MAIL CAMPAIGNS : DÉMARRAGE ===")

    total_campaigns = 0

    try:
        # --------------------------------------------------------
        # 1) Charger settings SMTP
        # --------------------------------------------------------
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")

        if not settings or not settings["mailing_enabled"]:
            msg = "Mailing désactivé → aucune action."
            log.warning(msg)
            task_logs(task_id, "info", msg)
            return

        # --------------------------------------------------------
        # 2) Campagnes en attente
        # --------------------------------------------------------
        campaigns = db.query("""
            SELECT * FROM mail_campaigns
            WHERE status='pending'
            ORDER BY created_at ASC
        """)

        if not campaigns:
            msg = "Aucune campagne en attente."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return

        total_campaigns = len(campaigns)
        log.info(f"{total_campaigns} campagne(s) en attente")

        # --------------------------------------------------------
        # 3) Traitement des campagnes
        # --------------------------------------------------------
        for camp in campaigns:
            camp_id = camp["id"]
            raw_subject = camp["subject"]
            raw_body = camp["body"]
            server_id = camp["server_id"]
            is_test = camp["is_test"]

            log.info(f"--- Campagne #{camp_id} ---")
            task_logs(task_id, "info", f"Traitement campagne #{camp_id}")

            db.execute(
                "UPDATE mail_campaigns SET status='sending' WHERE id=?",
                (camp_id,)
            )

            # ----------------------------------------------------
            # Destinataires
            # ----------------------------------------------------
            if is_test:
                recipients = [{
                    "id": 0,
                    "email": settings["admin_email"],
                    "username": "ADMIN",
                    "expiration_date": None
                }]
                log.info(f"Mode test → {settings['admin_email']}")
            else:
                if not server_id:
                    recipients = db.query("""
                        SELECT id, email, username, expiration_date
                        FROM vodum_users vu
                        WHERE vu.email IS NOT NULL
                          AND EXISTS (
                            SELECT 1
                            FROM media_users mu
                            WHERE mu.vodum_user_id = vu.id
                          )
                    """)
                else:
                    recipients = db.query("""
                        SELECT DISTINCT
                            vu.id AS id,
                            vu.email AS email,
                            vu.username AS username,
                            vu.expiration_date AS expiration_date
                        FROM vodum_users vu
                        JOIN media_users mu ON mu.vodum_user_id = vu.id
                        WHERE mu.server_id = ?
                          AND vu.email IS NOT NULL
                    """, (server_id,))


                log.info(f"{len(recipients)} destinataire(s) sélectionné(s)")

            sent_count = 0
            error_count = 0
            today = date.today()

            # ----------------------------------------------------
            # Boucle envoi emails
            # ----------------------------------------------------
            for user in recipients:
                email = user["email"]
                username = user["username"]
                exp_raw = user["expiration_date"]

                days_left = None
                if exp_raw:
                    try:
                        exp_date = datetime.fromisoformat(exp_raw).date()
                        days_left = (exp_date - today).days
                    except Exception:
                        pass

                context = build_user_context({
                    "username": username,
                    "email": email,
                    "expiration_date": exp_raw,
                    "days_left": days_left,
                })

                subject = render_mail(raw_subject, context)
                body = render_mail(raw_body, context)

                if send_email(settings, email, subject, body):
                    sent_count += 1
                else:
                    error_count += 1

            # ----------------------------------------------------
            # Campagne terminée
            # ----------------------------------------------------
            db.execute("""
                UPDATE mail_campaigns
                SET status='finished', finished_at=datetime('now')
                WHERE id=?
            """, (camp_id,))

            log.info(
                f"Campagne {camp_id} terminée → OK={sent_count}, ERR={error_count}"
            )

            task_logs(
                task_id,
                "info",
                f"Campagne {camp_id} → OK={sent_count}, ERR={error_count}"
            )

        task_logs(
            task_id,
            "success",
            f"{total_campaigns} campagne(s) traitée(s)"
        )

    except Exception as e:
        log.error("Erreur générale dans send_mail_campaigns", exc_info=True)
        task_logs(task_id, "error", f"Erreur send_mail_campaigns : {e}")
        raise

    finally:
        log.info("=== SEND MAIL CAMPAIGNS : FIN ===")

