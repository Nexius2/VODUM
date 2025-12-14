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
from db_utils import open_db
from tasks_engine import task_logs, run_task
from logging_utils import get_logger

log = get_logger("disable_expired_users")


def run(task_id=None, db=None):
    task_logs(task_id, "info", "Tâche disable_expired_users démarrée")
    log.info("=== DISABLE EXPIRED USERS : START ===")

    conn = open_db()
    conn.row_factory = __import__("sqlite3").Row
    cur = conn.cursor()

    today = date.today()

    try:
        # 1️⃣ Sélection des users expirés avec accès Plex
        users = cur.execute("""
            SELECT DISTINCT u.id, u.username
            FROM users u
            JOIN shared_libraries sl ON sl.user_id = u.id
            WHERE u.expiration_date IS NOT NULL
              AND date(u.expiration_date) < date(?)
        """, (today,)).fetchall()

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

            # Supprimer toutes les bibliothèques
            cur.execute(
                "DELETE FROM shared_libraries WHERE user_id = ?",
                (uid,)
            )

            # Créer un job SYNC pour chaque serveur Plex
            plex_servers = cur.execute(
                "SELECT id FROM servers WHERE type = 'plex'"
            ).fetchall()

            for s in plex_servers:
                cur.execute("""
                    INSERT INTO plex_jobs(action, user_id, server_id, library_id, processed)
                    VALUES ('sync', ?, ?, NULL, 0)
                """, (uid, s["id"]))

        conn.commit()

        # 3️⃣ Appliquer réellement côté Plex
        log.info("Lancement de apply_plex_access_updates")
        run_task("apply_plex_access_updates")

        msg = f"{len(users)} utilisateur(s) Plex désactivé(s)"
        log.info(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        conn.rollback()
        log.error("Erreur disable_expired_users", exc_info=True)
        task_logs(task_id, "error", f"Erreur disable_expired_users: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

        log.info("=== DISABLE EXPIRED USERS : END ===")
