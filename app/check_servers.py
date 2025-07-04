import sqlite3
import requests
import time
import threading
from logger import logger
from datetime import datetime, timedelta
#from app import update_task_status
import xml.etree.ElementTree as ET





DATABASE_PATH = "/app/appdata/database.db"
UPDATE_INTERVAL = 3600  # Temps en secondes, modifiable dans l'interface plus tard

def run():
    update_statuses()


def check_plex_server(url, token):
    try:
        res = requests.get(f"{url}/identity", headers={"X-Plex-Token": token}, timeout=5)
        if res.status_code == 200:
            return "🟢 OK"
        else:
            logger.error(f"[{url}] Erreur HTTP {res.status_code} lors de la connexion au serveur Plex.")
            return f"🔴 Erreur HTTP {res.status_code}"
    except requests.exceptions.ConnectTimeout:
        logger.warning(f"[{url}] Serveur Plex injoignable (délai de connexion dépassé). Vérifiez que le serveur est allumé et que le port {url.split(':')[-1]} est accessible.")
        return "🔴 Serveur injoignable (timeout)"
    except requests.exceptions.ReadTimeout:
        logger.warning(f"[{url}] Réponse trop lente du serveur Plex (read timeout). Vérifiez l’état réseau du serveur.")
        return "🔴 Réponse trop lente"
    except requests.exceptions.ConnectionError:
        logger.warning(f"[{url}] Impossible de se connecter au serveur Plex. Vérifiez l’état du serveur, la configuration réseau ou l’accès distant Plex.")
        return "🔴 Connexion impossible"
    except Exception as e:
        logger.warning(f"[{url}] Erreur inconnue lors de la connexion au serveur Plex : {e}")
        return "🔴 Erreur inconnue"



def check_tautulli(url, api_key):
    try:
        res = requests.get(f"{url}/api/v2?apikey={api_key}&cmd=status", timeout=5)
        return "🟢 OK" if res.status_code == 200 else "🔴 Erreur"
    except Exception:
        return "🔴 Injoignable"


def update_statuses():
    import xml.etree.ElementTree as ET
    from datetime import datetime
    
    last_checked = datetime.utcnow().isoformat()

    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute("SELECT id, plex_url, plex_token, tautulli_url, tautulli_api_key FROM servers")
    servers = cursor.fetchall()

    for sid, plex_url, plex_token, tautulli_url, tautulli_api_key in servers:
        if not plex_url or not plex_token:
            continue

        logger.info(f"🔍 Vérification du serveur ID={sid} ({plex_url})")
        server_id = None
        server_name = None
        plex_status = "🔴 Erreur"
        
        # ✅ Vérification Plex
        try:
            res = requests.get(f"{plex_url}/identity", headers={"X-Plex-Token": plex_token}, timeout=5)
            if res.status_code == 200:
                plex_status = "🟢 OK"
                xml = ET.fromstring(res.text)
                server_id = xml.attrib.get("machineIdentifier")
                logger.info(f"✅ machineIdentifier trouvé : {server_id}")
            else:
                logger.info(f"❌ /identity code {res.status_code}")
        except Exception as e:
            logger.error(f"❌ Erreur connexion Plex : {e}")
            plex_status = "🔴 Injoignable"
            
        # ✅ Récupération du nom via Plex.tv
        if server_id and not server_name:
            server_name = get_server_name_from_plex_tv(server_id, plex_token)
            logger.info(f"🔍 Nom récupéré via Plex.tv : {server_name}")

        # ✅ Vérification Tautulli
        if tautulli_url and tautulli_api_key:
            try:
                res = requests.get(f"{tautulli_url}/api/v2?apikey={tautulli_api_key}&cmd=status", timeout=5)
                tautulli_status = "🟢 OK" if res.status_code == 200 else "🔴 Erreur"
            except:
                tautulli_status = "🔴 Injoignable"
        else:
            tautulli_status = "⏸ Non configuré"

        # ✅ Mise à jour dans la base
        update_fields = [
            "plex_status = ?",
            "tautulli_status = ?",
            "last_checked = ?"
        ]
        params = [plex_status, tautulli_status, last_checked]

        # ⚠️ Ne pas écraser un server_id existant s’il est déjà utilisé ailleurs
        if server_id:
            cursor.execute("SELECT id FROM servers WHERE server_id = ? AND id != ?", (server_id, sid))
            conflict = cursor.fetchone()
            if conflict:
                logger.warning(f"❌ Conflit de server_id pour ID={sid} : déjà utilisé par ID={conflict[0]}")
            else:
                update_fields.append("server_id = ?")
                params.append(server_id)

        if server_name:
            update_fields.append("name = ?")
            params.append(server_name)

        params.append(sid)

        try:
            cursor.execute(f"""
                UPDATE servers
                SET {', '.join(update_fields)}
                WHERE id = ?
            """, params)
        except sqlite3.OperationalError as e:
            logger.error(f"❌ Base SQLite verrouillée : {e}")
            continue

    conn.commit()
    conn.close()
    logger.info("✅ Statuts et métadonnées mises à jour.")



def get_server_name_from_plex_tv(server_id, plex_token):
    import xml.etree.ElementTree as ET

    try:
        res = requests.get("https://plex.tv/api/resources?includeHttps=1", headers={"X-Plex-Token": plex_token}, timeout=30)
        res.raise_for_status()
        root = ET.fromstring(res.text)

        for device in root.findall("Device"):
            if device.get("provides") and "server" in device.get("provides") \
               and device.get("clientIdentifier") == server_id:
                return device.get("name")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du nom via Plex.tv : {e}")
    
    return None



def auto_check():
    while True:
        logger.info("🔄 Vérification automatique des serveurs...")
        update_statuses()
        logger.info(f"⏳ Prochaine vérification dans {UPDATE_INTERVAL // 60} min")
        logger.debug("📌 Tentative d'update_task_status pour check_servers")
        update_task_status("check_servers", UPDATE_INTERVAL)
        try:
            update_task_status("check_servers", UPDATE_INTERVAL)
            logger.debug("✅ Statut de tâche mis à jour pour check_servers")
        except Exception as e:
            logger.warning(f"⚠️ Échec update_task_status pour check_servers → {e}")

        time.sleep(UPDATE_INTERVAL)

def update_task_status(task_name):
    """
    Met à jour la table task_status avec l'heure du dernier run.
    """
    now = datetime.now()
    next_run = None  # Ou calcule-le si tu veux
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO task_status (name, last_run, next_run)
        VALUES (?, ?, ?)
    """, (task_name, now.isoformat(), next_run))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
    # Appelé à chaque cron : lance le refresh flag si besoin
    try:
        trigger_server_refresh_flag()
    except NameError:
        logger.warning("⚠️ trigger_server_refresh_flag() non défini/importé, appel ignoré.")





