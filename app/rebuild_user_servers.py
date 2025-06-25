import sqlite3
from logger import logger
from config import DATABASE_PATH

def rebuild_user_servers():
    logger.info("🔁 Reconstruction de la table user_servers depuis users/library_access + libraries...")
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()

    # Récupérer tous les utilisateurs avec des accès à des bibliothèques
    cursor.execute("SELECT id, username, library_access FROM users WHERE library_access IS NOT NULL AND library_access != ''")
    users = cursor.fetchall()

    inserts = 0
    for user_id, username, library_access in users:
        section_ids = [id_.strip() for id_ in library_access.split(',') if id_.strip()]

        for section_id in section_ids:
            # Trouver le server_id correspondant à ce section_id
            cursor.execute("SELECT server_id FROM libraries WHERE section_id = ?", (section_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"⚠️ section_id {section_id} introuvable pour {username}")
                continue

            server_id = row[0]

            # Insérer si non existant
            cursor.execute("""
                INSERT OR IGNORE INTO user_servers (
                    user_id, server_id, source,
                    allow_sync, allow_camera_upload, allow_channels,
                    filter_movies, filter_television, filter_music
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, server_id, "rebuild", 1, 0, 1, "", "", ""
            ))
            inserts += cursor.rowcount

    conn.commit()
    conn.close()
    logger.info(f"✅ Reconstruction terminée. {inserts} nouvelles associations ajoutées.")

if __name__ == "__main__":
    rebuild_user_servers()