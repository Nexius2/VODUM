# /app/check_libraries.py
import sqlite3
from logger import logger
from config import DATABASE_PATH
from plexapi.server import PlexServer
from tasks import update_task_status

def check_libraries():
    logger.info("📚 Vérification des bibliothèques Plex")

    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()

    # On récupère aussi servers.name pour l'affichage
    cursor.execute("""
        SELECT id,
               name,
               server_id,
               COALESCE(url, plex_url)   AS base_url,
               COALESCE(token, plex_token) AS token
        FROM servers
        WHERE LOWER(type)='plex'
    """)
    servers = cursor.fetchall()
    logger.info(f"🔧 {len(servers)} serveur(s) Plex trouvé(s) en base")

    if not servers:
        logger.warning("⚠️ Aucun serveur Plex configuré.")
        conn.close()
        return

    for srv_dbid, srv_name, server_identifier, base_url, token in servers:
        if not base_url or not token:
            logger.error(f"❌ Serveur {srv_name} (id={srv_dbid}) sans url/token — ignoré")
            continue

        logger.info(f"🔍 Vérification des bibliothèques pour {srv_name} ({base_url})")

        try:
            plex = PlexServer(base_url, token)
            plex_names = {s.title for s in plex.library.sections()}
            logger.info(
                f"📡 Bibliothèques trouvées sur Plex ({srv_name}): "
                f"{', '.join(sorted(plex_names)) if plex_names else '(aucune)'}"
            )
        except Exception as e:
            logger.error(f"❌ Connexion Plex échouée ({srv_name}, {base_url}) : {e}")
            continue

        # ⚠️ libraries.server_id = servers.server_id (hash unique Plex)
        cursor.execute("SELECT id, name FROM libraries WHERE server_id = ?", (server_identifier,))
        db_libraries = cursor.fetchall()
        db_names = {name for _, name in db_libraries}
        logger.info(
            f"💾 Bibliothèques en base ({srv_name}): "
            f"{', '.join(sorted(db_names)) if db_names else '(aucune)'}"
        )

        deleted = 0
        for lib_id, name in db_libraries:
            if name not in plex_names:
                logger.warning(f"🗑️ Suppression de la bibliothèque '{name}' du serveur {srv_name}")
                cursor.execute("DELETE FROM libraries WHERE id = ?", (lib_id,))
                conn.commit()
                deleted += 1

        if deleted == 0:
            logger.info(f"✅ Aucune bibliothèque à supprimer pour le serveur {srv_name}")
        else:
            logger.info(f"🗑️ {deleted} bibliothèque(s) supprimée(s) pour le serveur {srv_name}")

    # 🔧 Nettoyage des bibliothèques orphelines (aucun serveur correspondant)
    cursor.execute("""
        SELECT id, name, server_id
        FROM libraries
        WHERE server_id NOT IN (SELECT server_id FROM servers)
           OR server_id IS NULL
           OR server_id = ''
    """)
    orphans = cursor.fetchall()

    if orphans:
        for lib_id, name, server_id in orphans:
            logger.warning(f"🗑️ Bibliothèque orpheline trouvée : '{name}' (server_id={server_id})")
        cursor.executemany("DELETE FROM libraries WHERE id = ?", [(lib_id,) for lib_id, _, _ in orphans])
        conn.commit()
        logger.warning(f"🗑️ {len(orphans)} bibliothèque(s) orpheline(s) supprimée(s)")

    conn.close()
    update_task_status("check_libraries")
    logger.info("🏁 Vérification des bibliothèques terminée.")

if __name__ == "__main__":
    check_libraries()
