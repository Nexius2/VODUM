#!/usr/bin/env python3
"""
disable_expired_users.py
------------------------
✓ Désactive les accès Plex des utilisateurs expirés
✓ Indépendant du mailing
✓ Compatible multi-serveurs Plex
✓ S'appuie sur media_user_libraries + media_jobs
✓ Lance apply_plex_access_updates (via jobs 'sync')
"""

from datetime import date
from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("disable_expired_users")


def run(task_id: int, db):
    """
    Désactive les accès Plex des utilisateurs expirés
    - Compatible multi-serveurs Plex
    - S'appuie sur media_user_libraries + media_jobs
    """

    task_logs(task_id, "info", "Tâche disable_expired_users démarrée")
    log.info("=== DISABLE EXPIRED USERS : START ===")

    today = date.today()

    try:
        # 1️⃣ Sélection des media_users Plex appartenant à des vodum_users expirés
        #     ET qui ont encore au moins 1 library Plex en base.
        rows = db.query(
            """
            SELECT DISTINCT
                vu.id            AS vodum_user_id,
                vu.username      AS vodum_username,
                mu.id            AS media_user_id,
                mu.server_id     AS server_id
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            JOIN servers s_mu
                ON s_mu.id = mu.server_id
            JOIN media_user_libraries mul
                ON mul.media_user_id = mu.id
            JOIN libraries l
                ON l.id = mul.library_id
            JOIN servers s_lib
                ON s_lib.id = l.server_id
            WHERE vu.expiration_date IS NOT NULL
              AND date(vu.expiration_date) < date(?)
              AND mu.type = 'plex'
              AND s_mu.type = 'plex'
              AND s_lib.type = 'plex'
            """,
            (today.isoformat(),),
        )

        if not rows:
            msg = "Aucun utilisateur expiré avec accès Plex."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return

        # Pour message final (compter les vodum_users uniques)
        vodum_ids = sorted({r["vodum_user_id"] for r in rows})
        log.info(f"{len(vodum_ids)} utilisateur(s) expiré(s) à désactiver (Plex)")

        # 2️⃣ Pour chaque compte Plex (media_user) → supprimer accès en base + créer job revoke
        processed_media = 0
        created_jobs = 0

        for r in rows:
            vodum_user_id = r["vodum_user_id"]
            vodum_username = r["vodum_username"]
            media_user_id = r["media_user_id"]
            server_id = r["server_id"]

            log.info(
                f"[VODUM #{vodum_user_id}] Suppression accès Plex en base "
                f"(media_user_id={media_user_id}, server_id={server_id}, user={vodum_username})"
            )

            # Supprime uniquement les libs de CE serveur (ça évite d'effacer un autre serveur par erreur)
            db.execute(
                """
                DELETE FROM media_user_libraries
                WHERE media_user_id = ?
                  AND library_id IN (
                      SELECT id FROM libraries WHERE server_id = ?
                  )
                """,
                (media_user_id, server_id),
            )

            processed_media += 1

            # Crée un job 'revoke' générique pour appliquer la révocation côté Plex via apply_media_access_updates
            # IMPORTANT: on stocke l'utilisateur CANONIQUE (vodum_user_id), pas media_user_id.
            dedupe_key = f"plex:revoke:server={server_id}:vodum_user={vodum_user_id}"

            exists = db.query_one(
                """
                SELECT 1
                FROM media_jobs
                WHERE provider = 'plex'
                  AND action = 'revoke'
                  AND server_id = ?
                  AND vodum_user_id = ?
                  AND library_id IS NULL
                  AND processed = 0
                LIMIT 1
                """,
                (server_id, vodum_user_id),
            )

            if not exists:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_jobs(
                        provider, action,
                        vodum_user_id, server_id, library_id,
                        payload_json,
                        processed, success, attempts,
                        dedupe_key
                    )
                    VALUES (
                        'plex', 'revoke',
                        ?, ?, NULL,
                        NULL,
                        0, 0, 0,
                        ?
                    )
                    """,
                    (vodum_user_id, server_id, dedupe_key),
                )
                created_jobs += 1

        msg = (
            f"{len(vodum_ids)} utilisateur(s) Plex désactivé(s) "
            f"(comptes plex traités={processed_media}, jobs créés={created_jobs})"
        )
        log.info(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        log.error("Erreur dans disable_expired_users", exc_info=True)
        task_logs(task_id, "error", f"Erreur disable_expired_users : {e}")
        raise

    finally:
        log.info("=== DISABLE EXPIRED USERS : END ===")
