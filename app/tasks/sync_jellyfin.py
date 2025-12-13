import requests
from logging_utils import get_logger

logger = get_logger("sync_jellyfin_users")


def run(task_id, db=None):
    """
    Récupère les utilisateurs de tous les serveurs Jellyfin et les synchronise dans la DB.
    """
    cur = db.cursor()

    # Récupérer tous les serveurs Jellyfin
    cur.execute("SELECT id, name, url, token FROM servers WHERE type = 'jellyfin'")
    servers = cur.fetchall()

    if not servers:
        logger.info("Aucun serveur Jellyfin configuré.")
        return

    for srv in servers:
        server_id = srv["id"]
        url = srv["url"]
        token = srv["token"]

        if not url or not token:
            logger.warning(f"Serveur Jellyfin '{srv['name']}' incomplet (URL/token manquant).")
            continue

        api_url = f"{url}/Users?api_key={token}"

        logger.info(f"Récupération des utilisateurs Jellyfin depuis : {api_url}")

        try:
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            users = response.json()

        except Exception as e:
            logger.error(f"Erreur API Jellyfin ({srv['name']}): {e}")
            continue

        for u in users:
            jelly_id = u.get("Id")
            username = u.get("Name")

            if not jelly_id or not username:
                continue

            # Insérer ou mettre à jour l'utilisateur
            cur.execute("""
                INSERT INTO users (plex_id, username, status)
                VALUES (?, ?, 'active')
                ON CONFLICT(plex_id) DO UPDATE SET username=excluded.username
            """, (f"jellyfin_{jelly_id}", username))

            db.commit()

            user_id = cur.execute(
                "SELECT id FROM users WHERE plex_id = ?", (f"jellyfin_{jelly_id}",)
            ).fetchone()[0]

            # Associer utilisateur ↔ serveur Jellyfin
            cur.execute("""
                INSERT OR IGNORE INTO user_servers (user_id, server_id)
                VALUES (?, ?)
            """, (user_id, server_id))

            db.commit()

        logger.info(f"{len(users)} utilisateurs importés depuis {srv['name']}.")
