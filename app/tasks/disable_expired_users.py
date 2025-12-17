#!/usr/bin/env python3
"""
disable_expired_users.py
------------------------
✓ Désactive les accès Plex des utilisateurs expirés
✓ Indépendant du mailing
✓ Compatible multi-serveurs Plex
✓ S'appuie sur shared_libraries + plex_jobs
✓ Lance apply_plex_access_updates
"""

from datetime import date
from tasks_engine import task_logs
from logging_utils import get_logger


log = get_logger("disable_expired_users")

def run(task_id: int, db):
    """
    Désactive les accès Plex des utilisateurs expirés
    - Compatible multi-serveurs Plex
    - S'appuie sur shared_libraries + plex_jobs
    """

    task_logs(task_id, "info", "Tâche disable_expired_users démarrée")
    log.info("=== DISABLE EXPIRED USERS : START ===")

    today = date.today()

    try:
        # 1️⃣ Sélection des users expirés avec accès Plex
        users = db.query(
            """
            SELECT DISTINCT u.id, u.username
            FROM users u
            JOIN shared_libraries sl ON sl.user_id = u.id
            WHERE u.expiration_date IS NOT NULL
              AND date(u.expiration_date) < date(?)
            """,
            (today,)
        )

        if not users:
            msg = "Aucun utilisateur expiré avec accès Plex."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return

        log.info(f"{len(users)} utilisateur(s) expiré(s) à désactiver")

        # 2️⃣ Pour chaque user → supprimer accès
        for u in users:
            uid = u["id"]
            username = u["username"]

            log.info(f"[USER #{uid}] Suppression accès Plex ({username})")

            # Suppression des accès en base
            db.execute(
                "DELETE FROM shared_libraries WHERE user_id = ?",
                (uid,)
            )

            # Création des jobs Plex (sync)
            plex_servers = db.query(
                "SELECT id FROM servers WHERE type = 'plex'"
            )

            for s in plex_servers:
                db.execute(
                    """
                    INSERT INTO plex_jobs(action, user_id, server_id, library_id, processed)
                    VALUES ('sync', ?, ?, NULL, 0)
                    """,
                    (uid, s["id"])
                )

        msg = f"{len(users)} utilisateur(s) Plex désactivé(s)"
        log.info(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        log.error("Erreur dans disable_expired_users", exc_info=True)
        task_logs(task_id, "error", f"Erreur disable_expired_users : {e}")
        raise

    finally:
        log.info("=== DISABLE EXPIRED USERS : END ===")


