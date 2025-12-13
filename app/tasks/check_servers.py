#!/usr/bin/env python3

"""
check_servers.py - VERSION TXT LOGGING
--------------------------------------
✓ Tous les logs détaillés → TXT
✓ Plus aucune insertion dans la DB pour les logs
✓ Ultra stable (aucun database locked)
✓ task_logs() seulement pour START / SUCCESS / ERROR
✓ Compatibilité run(task_id, db=None)
"""

import requests
import urllib3
from datetime import datetime
from plexapi.server import PlexServer

from db_utils import open_db
from tasks_engine import safe_execute, task_logs
from logging_utils import get_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = get_logger("check_servers")   # Logger TXT haut niveau


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def jellyfin_get_status(base_url, token=None):
    """
    Retourne (status, server_name, machine_id, meta)
    meta contiendra la version Jellyfin si trouvée.
    """
    try:
        # /System/Ping → juste un test UP/DOWN
        r = requests.get(f"{base_url}/System/Ping", timeout=5)
        if r.status_code != 200:
            return ("down", None, None, f"Ping returned {r.status_code}")

        # Si on a un token → on peut récupérer plus d'infos
        if token:
            info = requests.get(
                f"{base_url}/System/Info",
                params={"api_key": token},
                timeout=5
            ).json()

            name = info.get("ServerName")
            mid = info.get("Id")
            version = info.get("Version")

            return ("up", name, mid, version)

        # Sinon seulement up/down
        return ("up", None, None, None)

    except Exception as e:
        return ("down", None, None, f"Jellyfin error: {e}")


def choose_server_base_url(server_row):
    url = server_row["url"] or server_row["local_url"] or server_row["public_url"]
    if not url:
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def plex_get_info(base_url, token):
    """Retourne (status, name, machine_id, meta)"""
    try:
        session = requests.Session()
        session.verify = False
        plex = PlexServer(base_url, token, session=session)
        return (
            "up",
            plex.friendlyName,
            plex.machineIdentifier,
            plex.version
        )
    except Exception as e:
        return ("down", None, None, f"PlexAPI error: {e}")


def check_generic_server(url):
    try:
        r = requests.get(url, timeout=5)
        return "up" if r.status_code < 400 else "down"
    except Exception:
        return "down"


# ------------------------------------------------------------
# MAIN TASK
# ------------------------------------------------------------

def check_servers(task_id=None):
    """Version stable, verbeuse et sans logs DB internes."""

    task_logs(task_id, "info", "Tâche check_servers démarrée")
    log.info("=== CHECK SERVERS : DÉMARRAGE ===")

    db = open_db()
    cur = db.cursor()

    try:
        # Charger les serveurs
        safe_execute(cur, "SELECT * FROM servers")
        servers = cur.fetchall()

        if not servers:
            log.warning("Aucun serveur trouvé dans la DB.")
            task_logs(task_id, "warning", "Aucun serveur trouvé.")
            return

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        for s in servers:
            sid = s["id"]
            old_name = s["name"]

            log.info(f"--- Analyse du serveur #{sid} ({old_name}) ---")

            base_url = choose_server_base_url(s)
            if not base_url:
                log.warning(f"Serveur #{sid} : aucune URL valide.")
                continue

            log.debug(f"URL choisie pour test : {base_url}")

            new_name = old_name
            machine_id = s["server_identifier"]
            status = "unknown"

            # ---------------------------------------------
            # SERVEUR PLEX
            # ---------------------------------------------
            if s["type"] == "plex" and s["token"]:
                log.debug("Serveur reconnu comme PLEX, test via plexapi…")

                status, found_name, found_mid, meta = plex_get_info(base_url, s["token"])

                log.info(
                    f"Résultat Plex : status={status}, name={found_name}, mid={found_mid}, meta={meta}"
                )

                if status == "up":
                    if found_name:
                        new_name = found_name

                    if found_mid and found_mid != machine_id:
                        log.info(
                            f"MachineIdentifier mis à jour pour serveur #{sid}: "
                            f"{machine_id} → {found_mid}"
                        )
                        safe_execute(
                            cur,
                            "UPDATE servers SET server_identifier=? WHERE id=?",
                            (found_mid, sid)
                        )

            # ---------------------------------------------------------
            # SERVEUR JELLYFIN
            # ---------------------------------------------------------
            elif s["type"] == "jellyfin":
                log.debug("Serveur reconnu comme JELLYFIN, test via /System/Ping…")

                status, found_name, found_mid, meta = jellyfin_get_status(base_url, s["token"])

                log.info(
                    f"Résultat Jellyfin : status={status}, name={found_name}, mid={found_mid}, meta={meta}"
                )

                if status == "up":
                    if found_name:
                        new_name = found_name

                    if found_mid and found_mid != machine_id:
                        safe_execute(
                            cur,
                            "UPDATE servers SET server_identifier=? WHERE id=?",
                            (found_mid, sid)
                        )


            # ---------------------------------------------
            # SERVEUR GENERIQUE
            # ---------------------------------------------
            else:
                log.debug("Serveur non-Plex → test générique HTTP…")
                status = check_generic_server(base_url)
                log.info(f"Résultat générique HTTP: status={status}")

            # ---------------------------------------------
            # Mise à jour du statut
            # ---------------------------------------------
            safe_execute(
                cur,
                "UPDATE servers SET status=?, last_checked=?, name=? WHERE id=?",
                (status, now, new_name, sid)
            )

            if new_name != old_name:
                log.info(f"Serveur #{sid} : nom mis à jour '{old_name}' → '{new_name}'")
            else:
                log.debug(f"Serveur #{sid} : nom inchangé ('{new_name}')")

        db.commit()
        log.info("=== CHECK SERVERS : TERMINÉ AVEC SUCCÈS ===")
        task_logs(task_id, "success", "Vérification des serveurs terminée")

    except Exception as e:
        log.error(f"Erreur pendant check_servers : {e}", exc_info=True)
        task_logs(task_id, "error", f"Erreur check_servers : {e}")

    finally:
        try:
            db.close()
        except:
            pass



def run(task_id=None, db=None):
    """
    Le scheduler passe parfois une DB, mais on ne l'utilise pas ici
    pour éviter les locks → on ouvre toujours notre propre DB.
    """
    check_servers(task_id)
    return "OK"


if __name__ == "__main__":
    check_servers()
