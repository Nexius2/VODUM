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

    # 👉 AJOUT ESSENTIEL : synchronise les accès utilisateurs depuis Plex
    try:
        sync_user_libraries_from_plex()
    except Exception as e:
        logger.error(f"❌ Erreur lors de sync_user_libraries_from_plex : {e}")

    conn.close()
    update_task_status("check_libraries")
    logger.info("🏁 Vérification des bibliothèques terminée.")



def sync_user_libraries_from_plex():
    import sqlite3
    from plexapi.server import PlexServer
    from config import DATABASE_PATH
    from logger import logger

    logger.info("🔄 Synchronisation des accès bibliothèques pour tous les utilisateurs Plex...")

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, plex_url, plex_token, server_id FROM servers WHERE type='plex'")
    servers = cur.fetchall()

    for srv in servers:
        logger.info(f"🖥️ Serveur {srv['server_id']} – {srv['plex_url']}")

        try:
            plex = PlexServer(srv["plex_url"], srv["plex_token"])
            account = plex.myPlexAccount()
        except Exception as e:
            logger.error(f"❌ Impossible de se connecter au serveur Plex : {e}")
            continue

        cur.execute("SELECT id, username FROM users")
        users = cur.fetchall()

        for user in users:
            username = user["username"]
            user_id = user["id"]

            try:
                plex_user = account.user(username)
            except:
                logger.warning(f"⚠️ Utilisateur {username} non trouvé sur Plex.")
                continue

            shared_sections = []
            for section in plex.library.sections():
                try:
                    if plex_user in section.sharedUsers:
                        shared_sections.append(section.title)
                except:
                    pass

            logger.info(f"👤 {username} → accès Plex : {shared_sections}")

            cur.execute("DELETE FROM user_libraries WHERE user_id=?", (user_id,))

            for title in shared_sections:
                cur.execute("""
                    SELECT id FROM libraries
                    WHERE name=? AND server_id=?
                """, (title, srv["server_id"]))
                row = cur.fetchone()
                if row:
                    cur.execute("""
                        INSERT INTO user_libraries (user_id, library_id)
                        VALUES (?, ?)
                    """, (user_id, row["id"]))

    conn.commit()
    conn.close()
    logger.info("✅ Synchronisation user_libraries terminée !")



if __name__ == "__main__":
    check_libraries()
    sync_user_libraries_from_plex()
