import time
import sqlite3
from datetime import datetime
from logger import logger

from config import DATABASE_PATH
from tasks import update_task_status
from plex_share_helper import disable_user_libraries

UPDATE_INTERVAL = 43200  # 12h

def disable_expired_users():
    while True:
        logger.debug("🚀 Thread disable_expired_users lancé")
        logger.info("🔁 Démarrage de la désactivation des utilisateurs expirés...")

        try:
            conn = sqlite3.connect(DATABASE_PATH, timeout=10)
            cursor = conn.cursor()

            cursor.execute("SELECT disable_on_expiry FROM settings LIMIT 1")
            if not cursor.fetchone()[0]:
                logger.info("⏸️ Option 'disable_on_expiry' désactivée. Reprise dans 12h.")
                conn.close()
                time.sleep(UPDATE_INTERVAL)
                continue

            cursor.execute("""
                SELECT id, username, library_access
                FROM users
                WHERE expiration_date IS NOT NULL
                  AND DATE(expiration_date) < DATE('now')
                  AND is_admin = 0
            """)
            expired_users = cursor.fetchall()

            if not expired_users:
                logger.info("✅ Aucun utilisateur expiré trouvé.")
                conn.close()
                time.sleep(UPDATE_INTERVAL)
                continue

            for user_id, username, access_str in expired_users:
                logger.info(f"🛑 Désactivation de {username} (ID {user_id})")

                if not access_str:
                    logger.warning(f"⚠️ Aucun accès enregistré dans 'library_access' pour {username}")
                    continue

                # Trouver un serveur Plex lié à une bibliothèque de cet utilisateur
                cursor.execute("""
                    SELECT DISTINCT s.name, s.plex_token, s.plex_url, s.server_id
                    FROM libraries l
                    JOIN servers s ON l.server_id = s.server_id
                    WHERE l.section_id IN (%s) AND s.type = 'plex'
                """ % ",".join("?" * len(access_str.split(','))),
                tuple(access_str.split(',')))
                row = cursor.fetchone()

                if not row:
                    logger.warning(f"❌ Aucun serveur Plex associé pour {username}")
                    continue

                server_name, token, url, server_id = row
                logger.info(f"➡️ Suppression de tous les accès pour {username} sur le serveur {server_name}")

                # Suppression de tous les partages
                success = disable_user_libraries(token, url, username, server_name, [])


                if success:
                    logger.info(f"✅ Accès supprimé pour {username}")
                else:
                    logger.warning(f"⚠️ Échec de la désactivation pour {username} sur {server_name}")

            update_task_status("disable_expired_users", UPDATE_INTERVAL)
            conn.close()

        except Exception as e:
            logger.exception(f"🚨 Erreur générale : {e}")
            update_task_status("disable_expired_users", "error")

        time.sleep(UPDATE_INTERVAL)
