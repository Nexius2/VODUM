import requests
import json
from logger import logger
import sqlite3
from config import DATABASE_PATH
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
import logging
import http.client as http_client
from plexapi.exceptions import NotFound, BadRequest
import xml.etree.ElementTree as ET



logging.getLogger("plexapi").setLevel(logging.DEBUG)
http_client.HTTPConnection.debuglevel = 1

def update_user_libraries(plex_token, shared_server_id, machine_id, library_names):
    """
    Met à jour les bibliothèques partagées à un utilisateur Plex.

    :param plex_token: Token Plex du propriétaire du serveur
    :param shared_server_id: ID du lien de partage (user + serveur)
    :param machine_id: ID unique du serveur Plex (machineIdentifier)
    :param library_names: Liste des bibliothèques à partager (ou [] pour tout retirer)
    :return: Tuple (status_code, message)
    """
    url = f"https://plex.tv/api/v2/shared_servers/{shared_server_id}"
    headers = {
        "X-Plex-Product": "Plex Web",
        "X-Plex-Version": "4.87.2",
        "X-Plex-Client-Identifier": "plex-discord-bot",
        "X-Plex-Platform": "Python",
        "X-Plex-Token": plex_token,
        "Content-Type": "application/json"
    }
    payload = {
        "machineIdentifier": machine_id,
        "librarySectionIds": library_names
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code in (200, 204):
            logger.info(f"✅ Partage mis à jour avec succès pour shared_server_id={shared_server_id}")
        else:
            logger.warning(f"⚠️ Erreur API Plex ({response.status_code}): {response.text}")
        return response.status_code, response.text
    except Exception as e:
        logger.error(f"❌ Exception lors de l'appel à l'API Plex : {e}")
        return None, str(e)


def create_or_update_share(plex_token, target_user_id, machine_id, library_names):
    url = "https://plex.tv/api/v2/shared_servers"
    headers = {
        "X-Plex-Product": "Plex Web",
        "X-Plex-Version": "4.87.2",
        "X-Plex-Client-Identifier": "plex-discord-bot",
        "X-Plex-Platform": "Python",
        "X-Plex-Token": plex_token,
        "Content-Type": "application/json"
    }
    payload = {
        "invitedId": target_user_id,  # au lieu de userID
        "machineIdentifier": machine_id,
        "libraryNames": library_names
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code in (200, 201):
            logger.info(f"✅ Partage JBOPS appliqué pour user={target_user_id}, serveur={machine_id}, bibliothèques={library_names}")
        else:
            logger.warning(f"⚠️ Erreur API Plex {response.status_code} → {response.text}")
        return response.status_code, response.text
    except Exception as e:
        logger.error(f"❌ Exception API Plex : {e}")
        return None, str(e)


def get_shared_server_id(plex_token, target_user_id, machine_id):
    """
    Récupère le shared_server_id pour un user et un serveur, en mimant un appel Plex Web.
    """
    url = "https://plex.tv/api/shared_servers"
    headers = {
        "X-Plex-Token": plex_token,
        "X-Plex-Product": "Plex Web",
        "X-Plex-Version": "4.87.2",
        "X-Plex-Client-Identifier": "plex-discord-bot",
        "X-Plex-Platform": "Chrome",
        "X-Plex-Platform-Version": "122.0",
        "X-Plex-Device": "Windows",
        "X-Plex-Device-Name": "Chrome",
        "X-Plex-Model": "bundled",
        "X-Plex-Features": "external-media,indirect-media",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.warning(f"⚠️ Impossible de récupérer les partages : {response.status_code} - {response.text}")
            return None

        shared_servers = response.json()
        for share in shared_servers:
            if (str(share.get("userID")) == str(target_user_id)
                    and share.get("machineIdentifier") == machine_id):
                return share.get("id")

        logger.info(f"ℹ️ Aucun partage trouvé pour userID={target_user_id} et machineID={machine_id}")
        return None

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des partages : {e}")
        return None


def disable_user_libraries(plex_token, plex_url, username, server_name, library_names):
    """
    Supprime l'accès d'un utilisateur à toutes les bibliothèques sur un serveur Plex spécifique (via IP/token).
    """
    try:
        from plexapi.server import PlexServer
        from plexapi.myplex import MyPlexAccount
        from plexapi.exceptions import NotFound, BadRequest

        logger.info(f"🔗 Connexion à PlexServer via URL '{plex_url}' et token...")
        plex = PlexServer(plex_url, plex_token)
        account = plex.myPlexAccount()

        logger.info(f"🔍 Recherche de l'utilisateur Plex '{username}' via myPlexAccount...")
        try:
            user = account.user(username)
            logger.info(f"✅ Utilisateur trouvé: {user.title} | ID: {user.id} | Email: {getattr(user, 'email', 'inconnu')}")
        except Exception as e:
            logger.warning(f"❌ Utilisateur '{username}' introuvable dans PlexAPI : {e}")
            return False

        logger.info(f"🆔 MachineIdentifier du serveur courant : {plex.machineIdentifier}")
        logger.info(f"🔁 Appel à updateFriend pour retirer tous les accès de {username} sur {server_name}...")

        # 1er essai: suppression classique
        result = account.updateFriend(user=user, server=plex.machineIdentifier, sections=[])
        logger.info(f"🔎 Retour updateFriend : {result}")

        # --- Vérification stricte AVANT/APRÈS ---
        try:
            user_shares = [u for u in account.users() if u.id == user.id]
            if user_shares:
                logger.warning(f"⚠️ {username} semble avoir ENCORE accès sur {server_name} après updateFriend.")

                # PATCH 1 : Refaire un updateFriend avec server=None (vieux bug PlexAPI parfois corrigé ainsi)
                try:
                    logger.info(f"🔁 Deuxième tentative updateFriend, server=None (reset global des accès)...")
                    result2 = account.updateFriend(user=user, server=None, sections=[])
                    logger.info(f"🔎 Retour updateFriend (server=None) : {result2}")
                except Exception as e:
                    logger.warning(f"⚠️ Echec updateFriend(server=None) pour {username} : {e}")

                # Vérifie encore une fois
                user_shares2 = [u for u in account.users() if u.id == user.id]
                if user_shares2:
                    logger.error(f"❌ Impossible de retirer l'accès Plex à {username} même après updateFriend global.")
                    # Ici tu peux, SI VOULU, proposer removeFriend en dernier recours
                    # logger.error(f"‼️ Suggestion: supprimer manuellement ce partage dans l’interface Plex, ou active le mode force-removeFriend.")
                    return False
                else:
                    logger.info(f"✅ Accès supprimé pour {username} après updateFriend global.")

            else:
                logger.info(f"✅ Accès supprimé pour {username} sur {server_name} (vérifié)")

        except Exception as e:
            logger.warning(f"Impossible de vérifier la liste des utilisateurs partagés : {e}")

        return True

    except (NotFound, BadRequest) as e:
        logger.warning(f"⚠️ Erreur PlexAPI pour {username} sur {server_name} : {e}")
        return False
    except Exception as e:
        logger.exception(f"❌ Exception PlexAPI pour {username} sur {server_name} : {e}")
        return False


def unshare_all_libraries(plex_token, plex_url, username):
    logger.info(f"🔒 Suppression de l'accès aux bibliothèques Plex pour {username} sans retirer l'amitié")

    try:
        from plex_api_share import update_server_share  # si tu as déjà ce module

        # Mettre un tableau vide supprime seulement les bibliothèques, pas l’amitié
        update_server_share(username, [], plex_token)

        logger.info(f"✅ Bibliothèques retirées pour {username} sans suppression du lien d’amitié.")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur lors du unshare partiel : {e}")
        return False



def share_user_libraries(plex_token, plex_url, username, section_ids):
    from plexapi.server import PlexServer
    try:
        plex = PlexServer(plex_url, plex_token)
        account = plex.myPlexAccount()
        user = account.user(username)
        account.updateFriend(user=user, server=plex, removeSections=True, sections=section_ids)
        logger.info(f"✅ Bibliothèques {section_ids} partagées à {username} sur {plex_url}")
        return True
    except Exception as e:
        logger.error(f"❌ Impossible de partager à {username} sur {plex_url}: {e}")
        return False

def set_user_libraries(plex_token, plex_url, username, library_names, allowSync, camera, channels, filterMovies, filterTelevision, filterMusic):
    """
    Partage (ou retire) les bibliothèques via leur nom.
    Si library_names est vide : retire tous les accès (unshare complet).
    """
    from plexapi.server import PlexServer
    plex = PlexServer(plex_url, plex_token)
    account = plex.myPlexAccount()
    logger.debug(f"[plex_share_helper] Recherche du user dans Plex avec username='{username}'")
    logger.debug(f"[plex_share_helper] Liste des users connus : {[u.title for u in account.users()]}")

    user = account.user(username)
    logger.info(f"Maj des accès Plex : user={username}, libraries={library_names}")
    account.updateFriend(
        user=user,
        server=plex,
        sections=library_names,  # Ici, une liste de noms !
        allowSync=allowSync,
        allowCameraUpload=camera,
        allowChannels=channels,
        filterMovies={},
        filterTelevision={},
        filterMusic={},
    )




def set_user_libraries_via_api(
    plex_token, plex_url, username, library_names,
    allowSync, camera, channels, filterMovies, filterTelevision, filterMusic
):
    headers = {
        "X-Plex-Token": plex_token,
        "Accept": "application/json",
    }

    # 1. Récupère l'user_id Plex cible via l'API Plex.tv (XML)
    users_url = "https://plex.tv/api/users"
    r = requests.get(users_url, headers=headers)
    logger.debug(f"[PlexAPI] /api/users code={r.status_code} content={r.text[:300]}")
    if r.status_code != 200:
        logger.error(f"[PlexAPI] Erreur HTTP {r.status_code} sur /api/users : {r.text[:300]}")
        raise Exception(f"Erreur HTTP {r.status_code} sur /api/users : {r.text[:300]}")

    try:
        tree = ET.fromstring(r.text)
        users_list = []
        for user_xml in tree.findall(".//User"):
            user = {
                "id": user_xml.attrib.get("id"),
                "title": user_xml.attrib.get("title"),
                "username": user_xml.attrib.get("username"),
                "email": user_xml.attrib.get("email"),
            }
            users_list.append(user)
    except Exception as e:
        logger.error(f"[PlexAPI] Echec parse XML (users): {e} - Response: {r.text[:300]}")
        raise Exception(f"[PlexAPI] Impossible de parser les users depuis /api/users. XML: {e}")

    user_id = None
    for u in users_list:
        if not u.get('id'):
            continue
        if u.get('username') == username or u.get('title') == username or u.get('email') == username:
            user_id = u['id']
            break
    if not user_id:
        logger.error(f"[PlexAPI] Impossible de trouver le user_id Plex pour username={username} (dans {users_list})")
        raise Exception(f"[PlexAPI] Impossible de trouver le user_id Plex pour username={username}")

    # 2. Récupère le vrai server_id Plex.tv à partir du machineIdentifier local
    libs_url = f"{plex_url.rstrip('/')}/library/sections"
    libs_r = requests.get(libs_url, headers=headers)
    logger.debug(f"[PlexAPI] /library/sections code={libs_r.status_code} content={libs_r.text[:300]}")
    if libs_r.status_code != 200:
        logger.error(f"[PlexAPI] Erreur HTTP {libs_r.status_code} sur /library/sections : {libs_r.text[:300]}")
        raise Exception(f"Erreur HTTP {libs_r.status_code} sur /library/sections : {libs_r.text[:300]}")
    # --- Bloc machine_identifier ROBUSTE ---
    machine_identifier = libs_r.json()['MediaContainer'].get('machineIdentifier')
    if not machine_identifier:
        # 2e essai : requête sur /
        root_url = f"{plex_url.rstrip('/')}/"
        root_r = requests.get(root_url, headers=headers)
        if root_r.status_code == 200:
            try:
                machine_identifier = root_r.json()['MediaContainer'].get('machineIdentifier')
            except Exception as e2:
                logger.warning(f"[PlexAPI] machineIdentifier pas trouvé dans / : {e2} | Contenu={root_r.text[:300]}")
        if not machine_identifier:
            logger.error(f"[PlexAPI] Impossible de trouver le machineIdentifier sur {plex_url}")
            raise Exception(f"[PlexAPI] Pas de machineIdentifier trouvé sur /library/sections ni / pour {plex_url}")
    try:
        all_libraries = libs_r.json()['MediaContainer']['Directory']
    except Exception as e:
        logger.error(f"[PlexAPI] Echec decode JSON: {e} - Response: {libs_r.text[:300]}")
        raise Exception(f"[PlexAPI] JSONDecodeError sur /library/sections : {e} - Contenu = {libs_r.text[:300]}")

    # Récupère le server_id sur plex.tv correspondant au bon machineIdentifier
    servers_url = "https://plex.tv/api/servers"
    s = requests.get(servers_url, headers=headers)
    try:
        stree = ET.fromstring(s.text)
        server_id = None
        for srv in stree.findall(".//Server"):
            if srv.attrib.get("machineIdentifier") == machine_identifier:
                server_id = srv.attrib.get("id")
                break
        if not server_id:
            logger.error(f"[PlexAPI] Impossible de trouver le server_id sur plex.tv pour machineIdentifier={machine_identifier}")
            raise Exception(f"Pas de server_id plex.tv pour machineIdentifier={machine_identifier}")
    except Exception as e:
        logger.error(f"[PlexAPI] Echec parse XML (servers): {e} - Response: {s.text[:300]}")
        raise Exception(f"[PlexAPI] Impossible de parser les serveurs plex.tv. XML: {e}")

    # Crée le mapping seulement pour les vrais dossiers
    name_to_id = {}
    for lib in all_libraries:
        title = lib.get('title')
        lid = lib.get('id')
        if title and lid:
            name_to_id[title] = str(lid)
        else:
            logger.warning(f"[PlexAPI] Section ignorée (pas d'id ou title): {lib}")

    section_ids = [name_to_id[n] for n in library_names if n in name_to_id]

    # 3. Prépare le body POUR PLEX.TV (pas pour l'API locale)
    data = {
        "shared_server": {
            "server_id": server_id,
            "library_section_ids": section_ids,
            "invited_id": user_id,
            "allowSync": int(allowSync),
            "allowCameraUpload": int(camera),
            "allowChannels": int(channels),
            "filterMovies": filterMovies or {},
            "filterTelevision": filterTelevision or {},
            "filterMusic": filterMusic or {},
        }
    }

    # 4. Envoie le POST vers l’API Plex.tv !
    share_url = "https://plex.tv/api/v2/shared_servers"
    resp = requests.post(share_url, headers=headers, json=data)
    logger.debug(f"[PlexAPI] POST {share_url} code={resp.status_code} content={resp.text[:300]}")
    if resp.status_code not in (200, 201):
        logger.error(f"[PlexAPI] Echec partage : code={resp.status_code} data={resp.text}")
        raise Exception(f"[PlexAPI] Echec partage : code={resp.status_code} data={resp.text}")
    return True



def share_user_libraries_plexapi(
    plex_url, plex_token, username, library_names,
    allowSync, camera, channels, filterMovies, filterTelevision, filterMusic
):
    import logging
    logger = logging.getLogger("plex_share")
    try:
        plex = PlexServer(plex_url, plex_token)
        account = plex.myPlexAccount()
        user = account.user(username)
        logger.info(f"[Plex] Found user: {user.title} ({user.email})")

        # Récupère les sections à partager
        sections = []
        for lib in plex.library.sections():
            if lib.title in library_names:
                sections.append(lib)
        logger.info(f"[Plex] Sections à partager: {[s.title for s in sections]}")

        if not sections:
            logger.info(f"[Plex] Unshare all libraries for user {username}")
            try:
                account.updateFriend(user=user, server=plex, removeSections=True, sections=[])
            except NotFound as e:
                # ⚠️ C'est ici qu'on ignore l'erreur connue
                logger.warning(f"[PlexAPI] NotFound (404) lors du unshare pour {username} : {e}. Supposé OK si le partage n'existait plus.")
        else:
            logger.info(f"[Plex] Share: {library_names} avec {username} (allowSync={allowSync}, camera={camera}, channels={channels})")
            try:
                account.updateFriend(
                    user=user,
                    server=plex,
                    sections=sections,
                    allowSync=allowSync,
                    allowCameraUpload=camera,
                    allowChannels=channels,
                    filterMovies=filterMovies or {},
                    filterTelevision=filterTelevision or {},
                    filterMusic=filterMusic or {},
                )
            except NotFound as e:
                logger.warning(f"[PlexAPI] NotFound (404) lors du partage pour {username} : {e}. C'est souvent un faux positif Plex.")
        return True
    except Exception as e:
        logger.error(f"[Plex] Erreur partage: {e}")
        raise

