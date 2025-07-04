import sqlite3
from datetime import datetime
from logger import logger

from config import DATABASE_PATH
from tasks import update_task_status
from plex_share_helper import unshare_all_libraries

def disable_expired_users():
    # Début du traitement, log pour suivi
    logger.debug("🚀 Script disable_expired_users lancé")
    logger.info("🔁 Démarrage de la désactivation des utilisateurs expirés...")

    try:
        # Connexion à la base SQLite
        conn = sqlite3.connect(DATABASE_PATH, timeout=10)
        cursor = conn.cursor()

        # Vérifie si l’option "désactiver à expiration" est activée dans les paramètres
        cursor.execute("SELECT disable_on_expiry FROM settings LIMIT 1")
        if not cursor.fetchone()[0]:
            logger.info("⏸️ Option 'disable_on_expiry' désactivée. (aucune action)")
            conn.close()
            update_task_status("disable_expired_users")  # Met à jour le statut de la tâche (suivi)
            return

        # Recherche tous les utilisateurs (non admin) expirés qui ont des accès à des bibliothèques
        cursor.execute("""
            SELECT id, username, library_access
            FROM users
            WHERE expiration_date IS NOT NULL
              AND DATE(expiration_date) < DATE('now')
              AND is_admin = 0
              AND library_access IS NOT NULL
              AND library_access != ''
        """)
        expired_users = cursor.fetchall()

        if not expired_users:
            logger.info("✅ Aucun utilisateur expiré trouvé.")
            conn.close()
            update_task_status("disable_expired_users")  # Rien à faire, on sort
            return

        # Pour chaque utilisateur expiré :
        for user_id, username, library_access in expired_users:
            logger.info(f"🛑 Désactivation de {username} (ID {user_id})")

            # Si aucune info d’accès, on log un warning et on saute
            if not library_access:
                logger.warning(f"⚠️ Aucun accès enregistré dans 'library_access' pour {username}")
                continue

            # Convertit la liste d’IDs des bibliothèques en tableau d’IDs valides
            access_ids = [id.strip() for id in library_access.split(',') if id.strip().isdigit()]

            if not access_ids:
                logger.warning(f"⚠️ Aucun access_id valide dans library_access pour {username}")
                continue

            # Recherche les serveurs Plex associés à ces bibliothèques
            query = """
                SELECT DISTINCT s.server_id, s.name, s.plex_token, s.plex_url
                FROM libraries l
                JOIN servers s ON l.server_id = s.server_id
                WHERE l.section_id IN ({seq}) AND s.type = 'plex'
            """.format(seq=','.join(['?']*len(access_ids)))
            cursor.execute(query, tuple(access_ids))
            servers = cursor.fetchall()
            logger.info(f"[DEBUG SQL] Serveurs trouvés pour {username}: {servers}")

            if not servers:
                logger.warning(f"❌ Aucun serveur Plex associé pour {username} (section_ids : {access_ids})")
                continue

            # Pour chaque serveur, retire les accès à toutes les bibliothèques pour cet utilisateur
            for server_id, server_name, token, url in servers:
                logger.info(f"➡️ Suppression de tous les accès pour {username} sur le serveur {server_name} ({url})")
                # Appel l’API Plex pour désactiver les accès
                success = unshare_all_libraries(token, url, username)
                if success:
                    logger.info(f"✅ Accès supprimé pour {username} sur {server_name}")
                else:
                    logger.warning(f"⚠️ Échec de la désactivation pour {username} sur {server_name}")

        # Met à jour le statut de la tâche (dans la table de suivi)
        update_task_status("disable_expired_users")
        conn.close()

    except Exception as e:
        # En cas d’erreur, log détaillé + met à jour le statut d’erreur pour la tâche
        logger.exception(f"🚨 Erreur générale : {e}")
        update_task_status("disable_expired_users", "error")

# Lance la fonction seulement si le script est exécuté en direct (et pas importé)
if __name__ == "__main__":
    disable_expired_users()
