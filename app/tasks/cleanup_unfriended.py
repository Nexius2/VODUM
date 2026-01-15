#!/usr/bin/env python3

"""
cleanup_unfriended.py — VERSION TXT LOGGING (corrigée)
------------------------------------------------------
✓ Tous les logs → fichiers TXT (/logs/app.log)
✓ Aucun log en DB sauf task_logs (UI)
✓ Évite totalement les locks SQLite
✓ Très verbeux (DEBUG, INFO, WARNING, ERROR)
✓ Connexion DB locale isolée (db_utils.open_db)

But :
- Trouver les comptes Plex (media_users.type='plex') avec role='friend'
- Qui n'ont AUCUNE bibliothèque (media_user_libraries) sur des serveurs Plex
- Les passer en role='unfriended'
"""

from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("cleanup_unfriended")


def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_unfriended started")
    log.info("=== CLEANUP UNFRIENDED : STRATING ===")

    try:
        log.debug("Searching for Plex 'friend' accounts without any Plex libraries…")

        # On travaille sur media_users (comptes sur serveurs)
        # car le rôle Plex est porté par media_users.role, pas par vodum_users.
        rows = db.query(
            """
            SELECT
                mu.id AS media_user_id,
                mu.vodum_user_id AS vodum_user_id,
                COALESCE(vu.username, mu.username) AS username,
                vu.email AS email
            FROM media_users mu
            JOIN vodum_users vu ON vu.id = mu.vodum_user_id
            JOIN servers s_mu ON s_mu.id = mu.server_id
            LEFT JOIN media_user_libraries mul ON mul.media_user_id = mu.id
            LEFT JOIN libraries l ON l.id = mul.library_id
            LEFT JOIN servers s_lib ON s_lib.id = l.server_id
            WHERE mu.type = 'plex'
              AND s_mu.type = 'plex'
              AND mu.role = 'friend'
            GROUP BY mu.id
            HAVING COUNT(
                DISTINCT CASE WHEN s_lib.type = 'plex' THEN mul.library_id END
            ) = 0
            """
        )

        if not rows:
            msg = "No Plex 'friend' accounts without any Plex libraries."
            log.info(msg)
            task_logs(task_id, "info", msg)
            log.info("=== CLEANUP UNFRIENDED : END ===")
            return

        media_user_ids = [r["media_user_id"] for r in rows]
        log.debug(f"{len(media_user_ids)} Account(s) detected : {media_user_ids}")

        # Mise à jour en base : on passe le ROLE du compte Plex en 'unfriended'
        log.debug("Updating the role of the affected Plex accounts…")

        db.executemany(
            """
            UPDATE media_users
            SET role = 'unfriended'
            WHERE id = ?
              AND type = 'plex'
            """,
            [(mid,) for mid in media_user_ids],
        )

        msg = (
            f"{len(media_user_ids)} Plex account(s) set to 'unfriended' "
            f"(No Plex libraries found)."
        )
        log.info(msg)
        task_logs(task_id, "success", msg)
        log.info("=== CLEANUP UNFRIENDED : FINISHED ===")

    except Exception as e:
        log.error(f"Error in cleanup_unfriended : {e}", exc_info=True)
        task_logs(task_id, "error", f"Error cleanup_unfriended : {e}")
        raise
