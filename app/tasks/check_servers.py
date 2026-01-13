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
from tasks_engine import task_logs
from logging_utils import get_logger



urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = get_logger("check_servers")   # Logger TXT haut niveau


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def jellyfin_get_status(base_url, token=None):
    try:
        log.debug(f"[JELLYFIN] ping url={base_url}/System/Ping")
        r = requests.get(f"{base_url}/System/Ping", timeout=5)
        log.debug(f"[JELLYFIN] ping status_code={r.status_code}")

        if r.status_code != 200:
            return ("down", None, None, f"Ping returned {r.status_code}")

        if token:
            log.debug(f"[JELLYFIN] info url={base_url}/System/Info (with api_key)")
            r2 = requests.get(
                f"{base_url}/System/Info",
                params={"api_key": token},
                timeout=5
            )
            log.debug(f"[JELLYFIN] info status_code={r2.status_code}")

            try:
                info = r2.json()
            except Exception as e:
                log.error("[JELLYFIN] invalid json from /System/Info", exc_info=True)
                return ("down", None, None, f"Invalid JSON: {e}")

            name = info.get("ServerName")
            mid = info.get("Id")
            version = info.get("Version")
            log.debug(f"[JELLYFIN] info parsed name={name} id={mid} version={version}")

            return ("up", name, mid, version)

        return ("up", None, None, None)

    except Exception as e:
        log.error("[JELLYFIN] exception", exc_info=True)
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
    try:
        log.debug(f"[PLEX] connecting base_url={base_url} token_present={bool(token)}")
        session = requests.Session()
        session.verify = False
        plex = PlexServer(base_url, token, session=session)
        log.debug(
            f"[PLEX] connected friendlyName={plex.friendlyName} "
            f"machineId={plex.machineIdentifier} version={plex.version}"
        )
        return ("up", plex.friendlyName, plex.machineIdentifier, plex.version)

    except Exception as e:
        log.error(f"[PLEX] failed base_url={base_url}", exc_info=True)
        return ("down", None, None, f"PlexAPI error: {e}")



def check_generic_server(url):
    try:
        r = requests.get(url, timeout=5)
        return "up" if r.status_code < 400 else "down"
    except Exception:
        return "down"




def run(task_id: int, db):
    """
    Tâche check_servers — version UNIFORME et FINALE
    DBManager fourni par tasks_engine
    """

    task_logs(task_id, "start", "Tâche check_servers démarrée")
    log.info("=== CHECK SERVERS : DÉMARRAGE ===")

    try:
        servers = db.query("SELECT * FROM servers")

        if not servers:
            log.warning("Aucun serveur trouvé dans la DB.")
            task_logs(task_id, "warning", "Aucun serveur trouvé.")
            return

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        for s in servers:
            s = dict(s) 
            sid = s["id"]
            old_name = s["name"]

            log.info(f"--- Analyse du serveur #{sid} ({old_name}) ---")

            base_url = choose_server_base_url(s)
            log.debug(
                f"[SERVER #{sid}] raw_urls="
                f"url={s.get('url')} local={s.get('local_url')} public={s.get('public_url')}"
            )
            log.debug(
                f"[SERVER #{sid}] chosen_base_url={base_url} type={s.get('type')} "
                f"has_token={bool(s.get('token'))} verify_ssl=disabled_for_plexapi"
            )

            if not base_url:
                log.warning(f"Serveur #{sid} : aucune URL valide.")
                
                log.debug(
                    f"[SERVER #{sid}] result status={status} old_name={old_name} new_name={new_name} "
                    f"machine_id(old)={machine_id} meta={meta}"
                )

                
                db.execute(
                    """
                    UPDATE servers
                    SET status=?, last_checked=?
                    WHERE id=?
                    """,
                    ("down", now, sid)
                )
                continue

            new_name = old_name
            machine_id = s["server_identifier"]
            status = "unknown"

            # -----------------------------
            # SERVEUR PLEX
            # -----------------------------
            if s["type"] == "plex" and s["token"]:
                status, found_name, found_mid, meta = plex_get_info(
                    base_url, s["token"]
                )

                if status == "up":
                    if found_name:
                        new_name = found_name
                    if found_mid and found_mid != machine_id:
                        db.execute(
                            "UPDATE servers SET server_identifier=? WHERE id=?",
                            (found_mid, sid)
                        )

            # -----------------------------
            # SERVEUR JELLYFIN
            # -----------------------------
            elif s["type"] == "jellyfin":
                status, found_name, found_mid, meta = jellyfin_get_status(
                    base_url, s["token"]
                )

                if status == "up":
                    if found_name:
                        new_name = found_name
                    if found_mid and found_mid != machine_id:
                        db.execute(
                            "UPDATE servers SET server_identifier=? WHERE id=?",
                            (found_mid, sid)
                        )

            # -----------------------------
            # SERVEUR GÉNÉRIQUE
            # -----------------------------
            else:
                status = check_generic_server(base_url)

            # -----------------------------
            # Mise à jour DB
            # -----------------------------
            db.execute(
                """
                UPDATE servers
                SET status=?, last_checked=?, name=?
                WHERE id=?
                """,
                (status, now, new_name, sid)
            )

        log.info("=== CHECK SERVERS : TERMINÉ AVEC SUCCÈS ===")
        task_logs(task_id, "success", "Vérification des serveurs terminée")

    except Exception as e:
        log.error("Erreur pendant check_servers", exc_info=True)
        task_logs(task_id, "error", f"Erreur check_servers : {e}")
        raise





