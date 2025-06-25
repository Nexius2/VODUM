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
    Supprime l'accès d'un utilisateur à toutes les bibliothèques sur un serveur Plex spécifique.
    """
    try:
        account = MyPlexAccount(token=plex_token)
        user = account.user(username)

        logger.info(f"🔍 Connexion à la ressource Plex '{server_name}'...")
        resource = account.resource(server_name)
        server = resource.connect()

        logger.info(f"🔁 Suppression du partage de {username} sur '{server_name}' via PlexAPI...")
        account.updateFriend(user=user, server=server.machineIdentifier, sections=[])

        logger.info(f"✅ Partage désactivé pour {username} sur {server_name}")
        return True

    except (NotFound, BadRequest) as e:
        logger.warning(f"⚠️ Erreur PlexAPI pour {username} sur {server_name}: {e}")
        return False
    except Exception as e:
        logger.exception(f"❌ Exception PlexAPI pour {username} sur {server_name}: {e}")
        return False



