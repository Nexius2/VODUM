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
from core.plex_rate_limit import install_plex_rate_limit


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



def choose_server_base_urls(server_row):
    urls = []

    for key in ("url", "local_url", "public_url"):
        url = (server_row.get(key) or "").strip().rstrip("/")
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        if url not in urls:
            urls.append(url)

    return urls


def plex_get_info(base_url, token):
    try:
        log.debug(f"[PLEX] connecting base_url={base_url} token_present={bool(token)}")
        session = requests.Session()
        session.verify = False
        install_plex_rate_limit(session, base_url)
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
    log.info("=== CHECK SERVERS : STARTING ===")

    try:
        servers = db.query("SELECT * FROM servers")

        if not servers:
            log.warning("No server found in the database.")
            task_logs(task_id, "warning", "No server found.")
            return

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        for s in servers:
            s = dict(s) 
            sid = s["id"]
            old_name = s["name"]

            log.info(f"--- Server analysis #{sid} ({old_name}) ---")

            base_urls = choose_server_base_urls(s)
            base_url = base_urls[0] if base_urls else None
            log.debug(
                f"[SERVER #{sid}] raw_urls="
                f"url={s.get('url')} local={s.get('local_url')} public={s.get('public_url')}"
            )
            log.debug(
                f"[SERVER #{sid}] chosen_base_url={base_url} type={s.get('type')} "
                f"has_token={bool(s.get('token'))} verify_ssl=disabled_for_plexapi"
            )

            if not base_url:
                log.warning(f"Server #{sid} : No valid URL.")

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
            server_version = None
            status = "unknown"

            # -----------------------------
            # SERVEUR PLEX
            # -----------------------------
            if s["type"] == "plex" and s["token"]:
                meta = None
                for candidate_url in base_urls:
                    status, found_name, found_mid, meta = plex_get_info(candidate_url, s["token"])
                    if status == "up":
                        base_url = candidate_url
                        break

                if status == "up":
                    server_version = meta
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
                meta = None
                for candidate_url in base_urls:
                    status, found_name, found_mid, meta = jellyfin_get_status(candidate_url, s["token"])
                    if status == "up":
                        base_url = candidate_url
                        break

                if status == "up":
                    server_version = meta
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
                SET status=?, last_checked=?, name=?, server_version=?
                WHERE id=?
                """,
                (status, now, new_name, server_version, sid)
            )

        log.info("=== CHECK SERVERS : COMPLETED SUCCESSFULLY ===")
        task_logs(task_id, "success", "Server check completed")

    except Exception as e:
        log.error("Error while check_servers", exc_info=True)
        task_logs(task_id, "error", f"Error check_servers : {e}")
        raise





