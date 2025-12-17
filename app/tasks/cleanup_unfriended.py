#!/usr/bin/env python3

"""
cleanup_unfriended.py — VERSION TXT LOGGING
-------------------------------------------
✓ Tous les logs → fichiers TXT (/logs/app.log)
✓ Aucun log en DB sauf task_logs (UI)
✓ Évite totalement les locks SQLite
✓ Très verbeux (DEBUG, INFO, WARNING, ERROR)
✓ Connexion DB locale isolée (db_utils.open_db)
"""

from tasks_engine import task_logs
from logging_utils import get_logger



log = get_logger("cleanup_unfriended")

def run(task_id: int, db):
    """
    - Trouve les users avec plex_role='friend'
    - Qui n'ont AUCUNE bibliothèque sur un serveur Plex
    - Les passe en plex_role='unfriended'
    """

    task_logs(task_id, "info", "Tâche cleanup_unfriended démarrée")
    log.info("=== CLEANUP UNFRIENDED : DÉMARRAGE ===")

    try:
        log.debug("Recherche des utilisateurs 'friend' sans bibliothèque Plex…")

        rows = db.query(
            """
            SELECT u.id, u.username
            FROM users u
            LEFT JOIN shared_libraries sl ON sl.user_id = u.id
            LEFT JOIN libraries l ON l.id = sl.library_id
            LEFT JOIN servers s ON s.id = l.server_id
            WHERE u.plex_role = 'friend'
            GROUP BY u.id
            HAVING COUNT(
                DISTINCT CASE WHEN s.type = 'plex' THEN sl.library_id END
            ) = 0
            """
        )

        if not rows:
            msg = "Aucun utilisateur 'friend' sans bibliothèque Plex."
            log.info(msg)
            task_logs(task_id, "info", msg)
            log.info("=== CLEANUP UNFRIENDED : FIN ===")
            return

        user_ids = [r["id"] for r in rows]
        log.debug(f"{len(user_ids)} utilisateur(s) détectés : {user_ids}")

        # Mise à jour en base
        log.debug("Mise à jour des statuts des utilisateurs concernés…")

        db.executemany(
            """
            UPDATE users
            SET
                plex_role = 'unfriended',
                last_status = COALESCE(last_status, 'friend'),
                status_changed_at = datetime('now')
            WHERE id = ?
            """,
            [(uid,) for uid in user_ids],
        )

        msg = (
            f"{len(user_ids)} utilisateur(s) passé(s) en 'unfriended' "
            f"(aucune bibliothèque Plex trouvée)."
        )

        log.info(msg)
        task_logs(task_id, "success", msg)
        log.info("=== CLEANUP UNFRIENDED : TERMINÉ ===")

    except Exception as e:
        log.error(f"Erreur dans cleanup_unfriended : {e}", exc_info=True)
        task_logs(task_id, "error", f"Erreur cleanup_unfriended : {e}")
        raise



