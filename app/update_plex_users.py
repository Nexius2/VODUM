import os
import sqlite3
import requests
import time
import threading  # Permet d'exécuter la tâche en arrière-plan
import xml.etree.ElementTree as ET
from logger import logger
#logger.setLevel(logging.DEBUG)
import threading
from datetime import datetime, timedelta
import rebuild_user_servers
#import logging




#from app import update_task_status




# Configuration

DATABASE_PATH = "/app/appdata/database.db"
UPDATE_INTERVAL = 43200  # Temps en secondes (ex: 3600s = 1h)

# Configuration du logging
#logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def auto_sync():
    while True:
        logger.info("🔄 Synchronisation automatique des utilisateurs Plex...")
        try:
            sync_plex_users()
            logger.info(f"⏳ Prochaine synchronisation dans {UPDATE_INTERVAL / 3600} heures...")
            logger.debug("📌 Tentative d'update_task_status pour sync_users")
            update_task_status("sync_users", UPDATE_INTERVAL)
            logger.debug("✅ Statut de tâche mis à jour pour sync_users")
        except Exception as e:
            logger.warning(f"⚠️ Erreur update_task_status: {e}")
        time.sleep(UPDATE_INTERVAL)


def update_task_status(task_name, interval_seconds):
    from config import DATABASE_PATH
    now = datetime.now()
    next_run = now + timedelta(seconds=interval_seconds)
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO task_status (name, last_run, next_run)
        VALUES (?, ?, ?)
    """, (task_name, now.isoformat(), next_run.isoformat()))
    conn.commit()
    conn.close()

def get_admin_id(token):
    url = "https://plex.tv/users/account"
    headers = {"X-Plex-Token": token}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        root = ET.fromstring(response.text)
        return int(root.attrib.get("id", -1))
    else:
        logger.warning(f"⚠️ Impossible de récupérer l'ID admin via /users/account (HTTP {response.status_code})")
        return -1


def initialize_database():
    """🗄️ Initialise la base de données en créant les tables si elles n'existent pas."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()

    # Vérifie si la table 'plex_stats' existe déjà
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plex_stats';")
    table_exists = cursor.fetchone()

    if table_exists:
        logger.info("✅ Table 'plex_stats' existe déjà, aucune création nécessaire.")
    else:
        logger.info("🆕 Création des tables depuis tables.sql...")
        with open("tables.sql", "r", encoding="utf-8") as f:
            cursor.executescript(f.read())

    #threading.Thread(target=auto_sync, daemon=True).start()
    conn.commit()
    conn.close()

def get_plex_servers():
    """Récupère la liste des serveurs Plex depuis la base SQLite (sans appel à l’API Plex)."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT server_id, name, plex_url, plex_token, plex_status,
               tautulli_url, tautulli_api_key, tautulli_status,
               local_url, public_url
        FROM servers
    """)

    rows = cursor.fetchall()
    conn.close()

    servers = []
    for row in rows:
        servers.append({
            "server_id": row[0],
            "name": row[1],
            "plex_url": row[2],
            "plex_token": row[3],
            "plex_status": row[4],
            "tautulli_url": row[5],
            "tautulli_api_key": row[6],
            "tautulli_status": row[7],
            "local_url": row[8],
            "public_url": row[9]
        })
    return servers

def discover_plex_servers():
    """Interroge l’API Plex pour détecter les serveurs liés au compte (utiliser lors de l'initialisation)."""
    servers = []
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT plex_token
        FROM servers
        WHERE plex_token IS NOT NULL AND plex_token != ''
    """)
    tokens = [row[0] for row in cursor.fetchall()]
    conn.close()

    for token in tokens:
        headers = {"X-Plex-Token": token}
        try:
            r = requests.get("https://plex.tv/api/resources?includeHttps=1", headers=headers)
            r.raise_for_status()
            root = ET.fromstring(r.text)

            for device in root.findall("Device"):
                if device.get("provides") and "server" in device.get("provides"):
                    server_id = device.get("clientIdentifier")
                    name = device.get("name")
                    #admin_id = get_admin_id(token)
                    token = device.get("accessToken") or token
                    connections = device.findall("Connection")
                    local_url = public_url = ""

                    for conn in connections:
                        if conn.get("local") == "1":
                            local_url = conn.get("uri")
                        else:
                            public_url = conn.get("uri")

                    servers.append({
                        "server_id": server_id,
                        "name": name,
                        "plex_url": public_url or local_url,
                        "plex_token": token,
                        "plex_status": "unknown",
                        "tautulli_url": "",
                        "tautulli_api_key": "",
                        "tautulli_status": "unknown",
                        "local_url": local_url,
                        "public_url": public_url
                    })

        except Exception as e:
            logger.warning(f"⚠️ Erreur de découverte avec token {token[:6]}... : {e}")

    return servers



def get_plex_users():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT name, plex_token
        FROM servers
        WHERE plex_status = '🟢 OK'
          AND plex_token IS NOT NULL
          AND plex_token != ''
    """)
    rows = cursor.fetchall()
    conn.close()

    users = {}
    utilisateurs_ignorés = []

    def fetch(endpoint, token):
        try:
            headers = {"X-Plex-Token": token}
            res = requests.get(endpoint, headers=headers)
            res.raise_for_status()
            return ET.fromstring(res.text).findall("User")
        except Exception as e:
            logger.warning(f"⚠ Échec de récupération depuis {endpoint} avec token {token[:6]}... : {e}")
            return []
            
    admin_id_map = {token: get_admin_id(token) for _, token in rows}

    for name, token in rows:
        account_url = "https://plex.tv/users/account"
        account_response = requests.get(account_url, headers={"X-Plex-Token": token})
        logger.debug(f"📡 Résultat /users/account pour {name} → HTTP {account_response.status_code}")
        logger.debug(account_response.content.decode() if account_response.ok else account_response.text)

        if account_response.status_code == 200:
            account_data = ET.fromstring(account_response.content)
            logger.debug(f"🧾 Contenu XML /users/account : {account_response.content.decode()}")
            owner_email = account_data.attrib.get("email")
            owner_username = account_data.attrib.get("username")
            owner_id = account_data.attrib.get("id")
            logger.debug(f"🔑 OWNER ID: {owner_id} / USERNAME: {owner_username} / EMAIL: {owner_email}")

        else:
            owner_email = owner_username = owner_id = None

        temp_users = {}

        for user in fetch("https://plex.tv/api/users", token) + fetch("https://plex.tv/api/home/users", token):
            username = user.get("username") or user.get("title") or "inconnu"
            email = user.get("email", "")
            thumb = user.get("thumb", "")
            user_id = str(user.get("id"))
            plex_id = user_id
            is_admin = user_id == str(admin_id_map.get(token, "-1"))





            logger.debug(f"🧪 CHECK {user.get('username')} / ID {user.get('id')} → ADMIN = {is_admin}")
            logger.debug(f"[{logger.name}][{logger.level}] 🧪 CHECK {user.get('username')} / ID {user.get('id')} → ADMIN = {is_admin}")



            key = (email or f"id_{user_id}").strip().lower()

            logger.debug(f"👥 Candidat utilisateur : username={username} / email={email} / id={plex_id}")
            if not (username or email):
                logger.warning(f"❌ Utilisateur ignoré : username/email manquant : {ET.tostring(user)}")
                utilisateurs_ignorés.append({
                    "id": plex_id,
                    "username": username,
                    "email": email
                })
                continue

            if key not in users:
                conn = sqlite3.connect(DATABASE_PATH, timeout=10)
                cursor = conn.cursor()
                cursor.execute("SELECT firstname, lastname, second_email FROM users WHERE plex_id = ?", (plex_id,))
                row = cursor.fetchone()
                conn.close()

                users[key] = {
                    "plex_id": plex_id,
                    "username": username,
                    "email": email,
                    "is_admin": is_admin,
                    "avatar": thumb,
                    "firstname": row[0] if row else "",
                    "lastname": row[1] if row else "",
                    "second_email": row[2] if row else "",
                    "unique_key": key
                }
            else:
                # ✅ Mise à jour si un autre serveur détecte l'utilisateur comme admin
                users[key]["is_admin"] = users[key]["is_admin"] or is_admin
             



            temp_users[key] = True

        logger.info(f"📡 {len(temp_users)} utilisateurs Plex récupérés sur {name}")

    if utilisateurs_ignorés:
        logger.warning(f"⚠ {len(utilisateurs_ignorés)} utilisateur(s) ignorés : {[u['email'] for u in utilisateurs_ignorés]}")

    return list(users.values())







def update_database(users, servers):
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()

    for srv in servers:
        if not srv.get("server_id"):
            logger.warning(f"❌ Serveur ignoré (server_id manquant) : {srv}")
            continue

        cursor.execute("""
            INSERT OR REPLACE INTO servers (
                server_id, name, plex_url, plex_token, plex_status,
                tautulli_url, tautulli_api_key, tautulli_status,
                local_url, public_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            srv["server_id"], srv["name"], srv["plex_url"], srv["plex_token"],
            srv["plex_status"], srv["tautulli_url"], srv["tautulli_api_key"],
            srv["tautulli_status"], srv["local_url"], srv["public_url"]
        ))

    for user in users:
        logger.debug(f"💾 Traitement utilisateur {user['username']} ({user['unique_key']})")
        logger.debug("📥 Insertion en base...")
        # On vérifie si un utilisateur avec ce plex_id existe
        cursor.execute("SELECT 1 FROM users WHERE plex_id = ?", (user["plex_id"],))
        exists = cursor.fetchone()

        if exists:
            # Mise à jour utilisateur existant (on NE TOUCHE PAS à expiration_date)
            cursor.execute("""
                UPDATE users SET
                    username = ?, email = ?, avatar = ?, is_admin = ?,
                    firstname = ?, lastname = ?, second_email = ?
                WHERE plex_id = ?
            """, (
                user["username"],
                user["email"],
                user.get("avatar", ""),
                int(user.get("is_admin", False)),
                user.get("firstname", ""),
                user.get("lastname", ""),
                user.get("second_email", ""),
                user["plex_id"]
            ))
        else:
            # Nouvel utilisateur → on fixe expiration_date = maintenant + 1 mois
            expiration_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

            cursor.execute("""
                INSERT INTO users (
                    plex_id, username, email, avatar, is_admin,
                    firstname, lastname, second_email, expiration_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user["plex_id"],
                user["username"],
                user["email"],
                user.get("avatar", ""),
                int(user.get("is_admin", False)),
                user.get("firstname", ""),
                user.get("lastname", ""),
                user.get("second_email", ""),
                expiration_date
            ))




        cursor.execute("SELECT id FROM users WHERE plex_id = ?", (user["plex_id"],))
        user_row = cursor.fetchone()
        if not user_row:
            continue

        user_db_id = user_row[0]
        seen_libs = set()
        linked_server_ids = set()

        # 🔄 Synchronisation des bibliothèques partagées pour cet utilisateur
        current_libs = user.get("libraries", [])
        current_section_ids = [int(lib["section_id"]) for lib in current_libs if lib.get("section_id")]
        
        # Récupérer les library_id déjà en base pour cet utilisateur
        cursor.execute("""
            SELECT l.id, l.section_id, l.server_id
            FROM libraries l
            JOIN user_libraries ul ON ul.library_id = l.id
            WHERE ul.user_id = ?
        """, (user_db_id,))
        existing_links = cursor.fetchall()
        
        existing_section_ids = set()
        section_to_library_id = {}
        for lib_id, section_id, server_id in existing_links:
            existing_section_ids.add(int(section_id))
            section_to_library_id[int(section_id)] = lib_id
        
        # ➕ Ajout des nouveaux liens
        for lib in current_libs:
            try:
                section_id = int(lib["section_id"])
            except:
                continue
            if section_id not in existing_section_ids:
                cursor.execute("SELECT id FROM libraries WHERE section_id = ? AND server_id = ?", (section_id, lib["server_id"]))
                row = cursor.fetchone()
                if row:
                    library_id = row[0]
                    cursor.execute("INSERT INTO user_libraries (user_id, library_id) VALUES (?, ?)", (user_db_id, library_id))

        # ➖ Suppression des liens obsolètes
        for section_id in existing_section_ids:
            if section_id not in current_section_ids:
                lib_id = section_to_library_id.get(section_id)
                if lib_id:
                    cursor.execute("DELETE FROM user_libraries WHERE user_id = ? AND library_id = ?", (user_db_id, lib_id))


        for lib in user.get("libraries", []):
            try:
                section_id = int(lib["section_id"])
            except (ValueError, TypeError):
                logger.warning(f"❌ section_id invalide : {lib.get('section_id')}")
                continue

            server_id = lib.get("server_id")
            if not server_id:
                logger.warning(f"❌ server_id manquant pour bibliothèque : {lib}")
                continue

            # Vérifie que ce serveur existe
            cursor.execute("SELECT id FROM servers WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"❌ Aucun serveur trouvé pour server_id = {server_id}")
                continue

            internal_server_id = row[0]
            key = (lib["name"], server_id)
            if key in seen_libs:
                continue
            seen_libs.add(key)
            linked_server_ids.add((server_id, internal_server_id))

            cursor.execute("""
                SELECT 1 FROM libraries WHERE name = ? AND server_id = ?
            """, key)
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO libraries (section_id, name, server_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(section_id, server_id) DO UPDATE SET
                        name = excluded.name
                """, (section_id, lib["name"], server_id))
                logger.info(f"➕ Nouvelle bibliothèque ajoutée : {lib['name']} (serveur: {server_id})")

        # ➕ Mise à jour du champ library_access
        cursor.execute("""
            SELECT l.section_id
            FROM libraries l
            JOIN user_libraries ul ON ul.library_id = l.id
            WHERE ul.user_id = ?
        """, (user_db_id,))
        lib_ids = [str(row[0]) for row in cursor.fetchall()]
        library_access_value = ",".join(lib_ids)
        cursor.execute("UPDATE users SET library_access = ? WHERE id = ?", (library_access_value, user_db_id))

        # Lien avec les serveurs vérifiés
        for server_id, internal_server_id in linked_server_ids:
            cursor.execute("""
                INSERT INTO user_servers (
                    user_id, server_id, source,
                    allow_sync, allow_camera_upload, allow_channels,
                    filter_movies, filter_television, filter_music
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, server_id) DO UPDATE SET
                    source = excluded.source,
                    allow_sync = excluded.allow_sync,
                    allow_camera_upload = excluded.allow_camera_upload,
                    allow_channels = excluded.allow_channels,
                    filter_movies = excluded.filter_movies,
                    filter_television = excluded.filter_television,
                    filter_music = excluded.filter_music
            """, (
                user_db_id, internal_server_id, "api",
                1, 0, 1, "", "", ""
            ))

    logger.info("✅ Commit effectué avec succès")
    conn.commit()
    conn.close()
    logger.info("✅ Base de données mise à jour avec succès.")




def get_all_sections(server_url, plex_token, server_id):
    import xml.etree.ElementTree as ET

    try:
        res = requests.get(f"{server_url}/library/sections", headers={"X-Plex-Token": plex_token}, timeout=10)
        res.raise_for_status()
        root = ET.fromstring(res.text)

        sections = []
        for section in root.findall("Directory"):
            sections.append({
                "section_id": section.attrib.get("key"),
                "name": section.attrib.get("title"),
                "server_id": server_id
            })
        return sections

    except Exception as e:
        logger.warning(f"⚠ Impossible de récupérer les bibliothèques de {server_url} : {e}")
        return []



def sync_plex_users():
    if threading.current_thread().name == "MainThread":
        logger.info("🔄 Synchronisation manuelle des utilisateurs Plex...")
    else:
        logger.info("🔄 Synchronisation automatique des utilisateurs Plex...")

    servers = get_plex_servers()
    users = get_plex_users()

    shared_libraries_map = {}
    all_libraries = []
    seen_libraries = set()

    for server in servers:
        if not server.get("server_id") or not server.get("plex_token") or not server.get("plex_url"):
            continue

        # 📚 Bibliothèques partagées par utilisateur
        shared = get_shared_libraries(server["server_id"], server["plex_token"])
        for uid, libs in shared.items():
            if uid not in shared_libraries_map:
                shared_libraries_map[uid] = []
            shared_libraries_map[uid].extend(libs)

            for lib in libs:
                key = (lib["section_id"], lib["server_id"])
                if key not in seen_libraries:
                    seen_libraries.add(key)
                    all_libraries.append(lib)

        # 📚 Toutes les bibliothèques du serveur
        all_sections = get_all_sections(server["plex_url"], server["plex_token"], server["server_id"])
        for lib in all_sections:
            key = (lib["section_id"], lib["server_id"])
            if key not in seen_libraries:
                seen_libraries.add(key)
                all_libraries.append(lib)

    # 💾 Insertion unique des bibliothèques
    if all_libraries:
        conn = sqlite3.connect(DATABASE_PATH, timeout=10)
        cursor = conn.cursor()
        for lib in all_libraries:
            try:
                section_id = int(lib["section_id"])
            except (ValueError, TypeError):
                continue

            cursor.execute("""
                SELECT 1 FROM libraries WHERE name = ? AND server_id = ?
            """, (lib["name"], lib["server_id"]))

            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO libraries (section_id, name, server_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(section_id, server_id) DO UPDATE SET
                        name = excluded.name
                """, (section_id, lib["name"], lib["server_id"]))

                logger.info(f"➕ Nouvelle bibliothèque ajoutée : {lib['name']} (serveur: {lib['server_id']})")

        conn.commit()
        conn.close()

    logger.info(f"🧪 shared_libraries_map contient {len(shared_libraries_map)} utilisateurs")
    logger.debug(f"🧪 Exemple clés: {list(shared_libraries_map.keys())[:5]}")

    for user in users:
        logger.debug(f"👤 Utilisateur: {user['username']} → Plex ID: {user['plex_id']}")
        user["libraries"] = shared_libraries_map.get(user["plex_id"], [])

    if users:
        update_database(users, servers)
        rebuild_user_servers.rebuild_user_servers()
        return "✅ Synchronisation terminée avec succès !"
    return "⚠ Aucune mise à jour effectuée (aucun utilisateur trouvé)."












def get_user_libraries(user_id, server_token, server_url):
    """
    Récupère les bibliothèques partagées avec un utilisateur spécifique depuis un serveur Plex local.
    :param user_id: ID de l'utilisateur Plex
    :param server_token: Jeton d'accès du serveur local
    :param server_url: URL locale du serveur Plex (ex: http://192.168.1.80:32400)
    :return: Liste de bibliothèques (dictionnaires avec 'section_id', 'name', 'server_id')
    """
    url = f"{server_url}/library/sections/shared?userID={user_id}"
    headers = {
        "X-Plex-Token": server_token
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        xml_data = ElementTree.fromstring(response.content)
        libraries = []

        for directory in xml_data.findall("Directory"):
            libraries.append({
                "section_id": directory.attrib.get("key"),
                "name": directory.attrib.get("title"),
                "server_id": None  # à remplir si besoin via correspondance
            })
        return libraries
    except Exception as e:
        logger.error(f"[ERROR] Impossible de récupérer les bibliothèques de l'utilisateur {user_id}: {e}")
        return []





def get_shared_libraries(server_id, plex_token):
    url = f"https://plex.tv/api/servers/{server_id}/shared_servers"
    headers = {"X-Plex-Token": plex_token}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        xml_root = ET.fromstring(response.text)

        shared_info = {}
        for shared in xml_root.findall("SharedServer"):
            user_id = shared.attrib["userID"]

            # 🔒 Sécurise que server_id est bien défini ici
            current_server_id = shared.attrib.get("machineIdentifier", server_id)

            if user_id not in shared_info:
                shared_info[user_id] = []

            for section in shared.findall("Section"):
                if section.attrib.get("shared") != "1":
                    continue  # 🔒 ignorer les bibliothèques non partagées

                shared_info[user_id].append({
                    "section_id": section.attrib["id"],
                    "name": section.attrib["title"],
                    "server_id": current_server_id
                })


        return shared_info

    except Exception as e:
        logger.error(f"❌ Impossible de récupérer les bibliothèques partagées du serveur {server_id} : {e}")
        return {}

# Lancer la synchronisation automatique
#initialize_database()


if __name__ == "__main__":
    #main()
    initialize_database()
    sync_plex_users()
    trigger_user_refresh_flag()
    trigger_library_refresh_flag()




