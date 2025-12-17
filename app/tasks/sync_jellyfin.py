
from typing import Any, Dict, List, Optional, Tuple

import requests

from logging_utils import get_logger


logger = get_logger("sync_jellyfin")


# ----------------------------
# Jellyfin API helpers
# ----------------------------

def _base_url(url: str) -> str:
    return (url or "").rstrip("/")


def _get_json(session: requests.Session, url: str, timeout: int = 20) -> Any:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _build_api_url(base: str, path: str, token: str) -> str:
    base = _base_url(base)
    if not path.startswith("/"):
        path = "/" + path
    # Jellyfin accepte api_key en query
    return f"{base}{path}?api_key={token}"


# ----------------------------
# DB helpers
# ----------------------------



def _get_jellyfin_servers(db):
    return db.query(
        "SELECT id, name, url, token FROM servers WHERE type = 'jellyfin'"
    )



def _upsert_user_by_jellyfin_id(db, jellyfin_id: str, username: str) -> int:
    row = db.query_one(
        "SELECT id FROM users WHERE jellyfin_id = ?",
        (jellyfin_id,),
    )

    if row:
        user_id = row["id"]
        db.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (username, user_id),
        )
        return user_id

    cur = db.execute(
        """
        INSERT INTO users (jellyfin_id, username, status)
        VALUES (?, ?, 'active')
        """,
        (jellyfin_id, username),
    )
    return int(cur.lastrowid)



def _upsert_library(db, server_id, section_id, name, lib_type) -> int:
    db.execute(
        """
        INSERT INTO libraries (server_id, section_id, name, type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(server_id, section_id) DO UPDATE SET
            name = excluded.name,
            type = excluded.type
        """,
        (server_id, section_id, name, lib_type),
    )

    row = db.query_one(
        "SELECT id FROM libraries WHERE server_id = ? AND section_id = ?",
        (server_id, section_id),
    )
    return int(row["id"])



def _set_user_server_state(
    db,
    user_id,
    server_id,
    owned,
    all_libraries,
    num_libraries,
    last_seen_at,
):
    db.execute(
        """
        INSERT INTO user_servers (
            user_id, server_id,
            owned, all_libraries, num_libraries,
            pending, last_seen_at,
            source
        )
        VALUES (?, ?, ?, ?, ?, 0, ?, 'jellyfin_api')
        ON CONFLICT(user_id, server_id) DO UPDATE SET
            owned = excluded.owned,
            all_libraries = excluded.all_libraries,
            num_libraries = excluded.num_libraries,
            pending = excluded.pending,
            last_seen_at = COALESCE(excluded.last_seen_at, user_servers.last_seen_at),
            source = excluded.source
        """,
        (user_id, server_id, owned, all_libraries, num_libraries, last_seen_at),
    )



def _refresh_shared_libraries_for_server(db, user_id, server_id, allowed_library_ids):
    db.execute(
        """
        DELETE FROM shared_libraries
        WHERE user_id = ?
          AND library_id IN (
              SELECT id FROM libraries WHERE server_id = ?
          )
        """,
        (user_id, server_id),
    )

    for lib_id in allowed_library_ids:
        db.execute(
            """
            INSERT OR IGNORE INTO shared_libraries (user_id, library_id)
            VALUES (?, ?)
            """,
            (user_id, lib_id),
        )



# ----------------------------
# Jellyfin sync steps
# ----------------------------

def _sync_libraries_for_server(
    session: requests.Session,
    db,
    server_id: int,
    url: str,
    token: str,
) -> Dict[str, int]:
    """
    Récupère les VirtualFolders et les upsert dans libraries.
    Retourne un mapping {ItemId -> libraries.id}
    """
    api_url = _build_api_url(url, "/Library/VirtualFolders", token)
    logger.info(f"Jellyfin libraries: GET {api_url}")

    data = _get_json(session, api_url, timeout=30)
    mapping: Dict[str, int] = {}

    for vf in data or []:
        item_id = vf.get("ItemId")
        name = vf.get("Name")

        opts = vf.get("LibraryOptions") or {}
        lib_type = opts.get("CollectionType")

        if not item_id or not name:
            continue

        lib_db_id = _upsert_library(db, server_id, str(item_id), str(name), lib_type)
        mapping[str(item_id)] = lib_db_id

    logger.info(
        f"Jellyfin libraries: {len(mapping)} importées/mises à jour (server_id={server_id})"
    )
    return mapping


def _sync_users_and_policies_for_server(
    session: requests.Session,
    db,
    server_id: int,
    url: str,
    token: str,
    lib_map_itemid_to_dbid: Dict[str, int],
) -> Tuple[int, int]:
    """
    - Récupère tous les users
    - Pour chacun, récupère /Users/{id} pour Policy
    - Met à jour users, user_servers, shared_libraries
    """
    users_url = _build_api_url(url, "/Users", token)
    logger.info(f"Jellyfin users: GET {users_url}")

    users = _get_json(session, users_url, timeout=30) or []
    processed = 0
    policy_ok = 0

    for u in users:
        jellyfin_id = u.get("Id")
        username = u.get("Name")
        if not jellyfin_id or not username:
            continue

        jellyfin_id = str(jellyfin_id)
        username = str(username)

        user_id = _upsert_user_by_jellyfin_id(db, jellyfin_id, username)

        # Policy (plus fiable via /Users/{id})
        detail_url = _build_api_url(url, f"/Users/{jellyfin_id}", token)
        try:
            detail = _get_json(session, detail_url, timeout=30) or {}
            policy_ok += 1
        except Exception as e:
            logger.warning(
                f"Impossible de récupérer Policy pour user={username} ({jellyfin_id}) "
                f"sur server_id={server_id}: {e}"
            )
            detail = {}

        policy = (
            (detail.get("Policy") or u.get("Policy") or {})
            if isinstance(detail, dict)
            else {}
        )

        is_admin = 1 if policy.get("IsAdministrator") else 0
        enable_all = 1 if policy.get("EnableAllFolders") else 0
        enabled_folders = policy.get("EnabledFolders") or []

        # last activity info (si présent)
        last_seen_at = None
        if isinstance(detail, dict):
            last_seen_at = (
                detail.get("LastActivityDate")
                or detail.get("LastLoginDate")
                or u.get("LastActivityDate")
                or u.get("LastLoginDate")
            )

        # num_libraries
        if enable_all:
            num_libs = len(lib_map_itemid_to_dbid)
        else:
            num_libs = len(enabled_folders) if isinstance(enabled_folders, list) else 0

        _set_user_server_state(
            db=db,
            user_id=user_id,
            server_id=server_id,
            owned=is_admin,
            all_libraries=enable_all,
            num_libraries=num_libs,
            last_seen_at=last_seen_at,
        )

        # shared_libraries: sync de l’état réel
        allowed_db_lib_ids: List[int] = []

        if enable_all:
            # accès global -> on nettoie les entrées spécifiques pour ce serveur
            _refresh_shared_libraries_for_server(db, user_id, server_id, allowed_db_lib_ids)
        else:
            if isinstance(enabled_folders, list):
                for folder_item_id in enabled_folders:
                    key = str(folder_item_id)
                    lib_db_id = lib_map_itemid_to_dbid.get(key)
                    if lib_db_id:
                        allowed_db_lib_ids.append(lib_db_id)

            _refresh_shared_libraries_for_server(db, user_id, server_id, allowed_db_lib_ids)

        processed += 1

    logger.info(
        f"Jellyfin users/policies: {processed} users traités, policy récupérée pour {policy_ok} users "
        f"(server_id={server_id})"
    )
    return processed, policy_ok



# ----------------------------
# Public task entrypoint
# ----------------------------
def run(task_id: int, db):
    """
    Synchronisation complète Jellyfin (lecture seule côté Jellyfin)
    - Users
    - Libraries (VirtualFolders)
    - Policies
    - user_servers + shared_libraries côté DB
    """

    #task_logs(task_id, "info", "Tâche sync_jellyfin démarrée")
    logger.info("=== SYNC JELLYFIN : START ===")

    servers = _get_jellyfin_servers(db)
    if not servers:
        msg = "Aucun serveur Jellyfin configuré."
        logger.info(msg)
        #task_logs(task_id, "info", msg)
        logger.info("=== SYNC JELLYFIN : END ===")
        return

    total_users = 0
    total_policy_ok = 0
    total_libraries = 0

    session = requests.Session()

    try:
        any_success = False

        for srv in servers:
            server_id = int(srv["id"])
            name = srv["name"] or f"server_{server_id}"
            url = srv["url"]
            token = srv["token"]

            if not url or not token:
                logger.warning(
                    f"Serveur Jellyfin '{name}' incomplet (URL/token manquant)."
                )
                continue

            logger.info(f"--- Sync Jellyfin: {name} (server_id={server_id}) ---")

            try:
                # 1) Libraries
                lib_map = _sync_libraries_for_server(
                    session, db, server_id, url, token
                )
                total_libraries += len(lib_map)

                # 2) Users + Policies + Access sync
                processed, policy_ok = _sync_users_and_policies_for_server(
                    session=session,
                    db=db,
                    server_id=server_id,
                    url=url,
                    token=token,
                    lib_map_itemid_to_dbid=lib_map,
                )

                total_users += processed
                total_policy_ok += policy_ok

                logger.info(f"Sync Jellyfin OK pour '{name}'.")
                any_success = True

            except Exception as e:
                logger.error(
                    f"Erreur sync Jellyfin sur '{name}' (server_id={server_id}): {e}",
                    exc_info=True
                )
                continue

        if not any_success:
            raise RuntimeError("Aucun serveur Jellyfin n'a pu être synchronisé")

        # ✔ Succès scheduler
        logger.info(
            f"Sync Jellyfin OK — users={total_users}, libraries={total_libraries}"
        )


    except Exception as e:
        logger.error("Erreur globale sync_jellyfin", exc_info=True)
        #task_logs(task_id, "error", f"Erreur sync_jellyfin : {e}")
        raise

    finally:
        try:
            session.close()
        except Exception:
            pass

        logger.info(
            f"Sync Jellyfin terminé. users={total_users}, "
            f"policies_ok={total_policy_ok}, libraries_seen={total_libraries}"
        )
        logger.info("=== SYNC JELLYFIN : END ===")
