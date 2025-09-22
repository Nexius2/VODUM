import os
import time
import sqlite3
import requests
from logger import logger
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

# --- Configuration ---
DATABASE_PATH = "/app/appdata/database.db"
UPDATE_INTERVAL = 3600  # utilisé seulement par auto_check()
BASE_URL = os.getenv("VODUM_API_BASE", "http://127.0.0.1:5000")


# --- Helpers DB ---
def open_db():
    """Connexion courte et robuste à SQLite."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # réduire les locks
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


# --- Notif UI ---
def trigger_refresh_servers():
    """Demande au serveur Flask de rafraîchir la page Serveurs."""
    try:
        requests.post(f"{BASE_URL}/api/trigger-refresh/servers", timeout=2)
    except Exception:
        # ne pas casser le script juste pour la notif UI
        pass


# --- Checks externes ---
def check_plex_server(url, token):
    try:
        res = requests.get(f"{url}/identity", headers={"X-Plex-Token": token}, timeout=5)
        if res.status_code == 200:
            return "🟢 OK"
        else:
            logger.error(f"[{url}] Erreur HTTP {res.status_code} lors de la connexion au serveur Plex.")
            return f"🔴 Erreur HTTP {res.status_code}"
    except requests.exceptions.ConnectTimeout:
        logger.warning(f"[{url}] Serveur Plex injoignable (timeout).")
        return "🔴 Serveur injoignable (timeout)"
    except requests.exceptions.ReadTimeout:
        logger.warning(f"[{url}] Réponse trop lente du serveur Plex (read timeout).")
        return "🔴 Réponse trop lente"
    except requests.exceptions.ConnectionError:
        logger.warning(f"[{url}] Connexion impossible au serveur Plex.")
        return "🔴 Connexion impossible"
    except Exception as e:
        logger.warning(f"[{url}] Erreur inconnue connexion Plex : {e}")
        return "🔴 Erreur inconnue"


def check_tautulli(url, api_key):
    try:
        res = requests.get(f"{url}/api/v2?apikey={api_key}&cmd=status", timeout=5)
        return "🟢 OK" if res.status_code == 200 else "🔴 Erreur"
    except Exception:
        return "🔴 Injoignable"


def get_server_name_from_plex_tv(server_id, plex_token):
    try:
        res = requests.get(
            "https://plex.tv/api/resources?includeHttps=1",
            headers={"X-Plex-Token": plex_token},
            timeout=30,
        )
        res.raise_for_status()
        root = ET.fromstring(res.text)
        for device in root.findall("Device"):
            if device.get("provides") and "server" in device.get("provides") \
               and device.get("clientIdentifier") == server_id:
                return device.get("name")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du nom via Plex.tv : {e}")
    return None


# --- Coeur du job ---
def update_statuses():
    """Vérifie chaque serveur et met à jour la table servers."""
    now_utc = datetime.now(timezone.utc)
    last_checked = now_utc.isoformat()

    conn = open_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, plex_url, plex_token, tautulli_url, tautulli_api_key, name FROM servers")
    servers = cursor.fetchall()

    for row in servers:
        sid = row["id"]
        plex_url = row["plex_url"]
        plex_token = row["plex_token"]
        tautulli_url = row["tautulli_url"]
        tautulli_api_key = row["tautulli_api_key"]

        if not plex_url or not plex_token:
            # Serveur non configuré côté Plex
            logger.info(f"⏭️ Serveur ID={sid} ignoré (Plex non configuré).")
            plex_status = "⏸ Non configuré"
            tautulli_status = "⏸ Non configuré" if not tautulli_url or not tautulli_api_key else "🔴 Erreur"
            cursor.execute(
                """
                UPDATE servers
                   SET plex_status = ?,
                       tautulli_status = ?,
                       last_checked = ?
                 WHERE id = ?
                """,
                (plex_status, tautulli_status, last_checked, sid),
            )
            continue

        logger.info(f"🔍 Vérification du serveur ID={sid} ({plex_url})")

        server_id = None
        server_name = None

        # ✅ Vérif Plex /identity
        try:
            res = requests.get(f"{plex_url}/identity", headers={"X-Plex-Token": plex_token}, timeout=5)
            if res.status_code == 200:
                plex_status = "🟢 OK"
                xml = ET.fromstring(res.text)
                server_id = xml.attrib.get("machineIdentifier")
                logger.info(f"✅ machineIdentifier : {server_id}")
            else:
                plex_status = f"🔴 HTTP {res.status_code}"
                logger.info(f"❌ /identity code {res.status_code}")
        except Exception as e:
            logger.error(f"❌ Erreur connexion Plex : {e}")
            plex_status = "🔴 Injoignable"

        # ✅ Nom via Plex.tv si on a l'identifiant
        if server_id:
            name = get_server_name_from_plex_tv(server_id, plex_token)
            if name:
                server_name = name
                logger.info(f"🔎 Nom (plex.tv): {server_name}")

        # ✅ Vérif Tautulli
        if tautulli_url and tautulli_api_key:
            try:
                tres = requests.get(f"{tautulli_url}/api/v2?apikey={tautulli_api_key}&cmd=status", timeout=5)
                tautulli_status = "🟢 OK" if tres.status_code == 200 else "🔴 Erreur"
            except Exception:
                tautulli_status = "🔴 Injoignable"
        else:
            tautulli_status = "⏸ Non configuré"

        # ✅ Update en base
        update_fields = [
            "plex_status = ?",
            "tautulli_status = ?",
            "last_checked = ?",
        ]
        params = [plex_status, tautulli_status, last_checked]

        # server_id: seulement si pas de conflit
        if server_id:
            cursor.execute("SELECT id FROM servers WHERE server_id = ? AND id != ?", (server_id, sid))
            conflict = cursor.fetchone()
            if conflict:
                logger.warning(f"⚠️ Conflit server_id pour ID={sid} : déjà utilisé par ID={conflict['id']}")
            else:
                update_fields.append("server_id = ?")
                params.append(server_id)

        if server_name:
            update_fields.append("name = ?")
            params.append(server_name)

        params.append(sid)
        try:
            cursor.execute(f"UPDATE servers SET {', '.join(update_fields)} WHERE id = ?", params)
        except sqlite3.OperationalError as e:
            logger.error(f"❌ SQLite verrouillée lors de l’update serveur ID={sid} : {e}")
            continue

    conn.commit()
    conn.close()
    logger.info("✅ Statuts et métadonnées mises à jour.")

    # Notifie l’UI (flag refresh)
    trigger_refresh_servers()


# --- Suivi d'exécution ---
def update_task_status(task_name: str):
    """Marque la dernière exécution de la tâche dans task_status."""
    try:
        conn = open_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO task_status (name, last_run, next_run)
            VALUES (?, ?, NULL)
            """,
            (task_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"⚠️ Impossible de mettre à jour task_status pour {task_name} : {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# --- Boucle auto si besoin (pas utilisée par le cron) ---
def auto_check():
    while True:
        logger.info("🔄 Vérification automatique des serveurs...")
        update_statuses()
        update_task_status("check_servers")
        logger.info(f"⏳ Prochaine vérification dans {UPDATE_INTERVAL // 60} min")
        time.sleep(UPDATE_INTERVAL)


# --- Entrée principale ---
def main():
    update_statuses()
    update_task_status("check_servers")


if __name__ == "__main__":
    main()
