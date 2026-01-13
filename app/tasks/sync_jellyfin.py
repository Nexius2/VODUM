from typing import Any, Dict, List, Optional, Tuple

import json
import requests
from datetime import datetime, timedelta

from logging_utils import get_logger


logger = get_logger("sync_jellyfin")


# ----------------------------
# helpers
# ----------------------------

def ensure_expiration_date_on_first_access(db, vodum_user_id: int) -> bool:
    """
    Initialise expiration_date UNIQUEMENT si :
      - expiration_date est NULL
      - default_subscription_days > 0

    ⚠️ Sur la DB v2, l'expiration est portée par vodum_users (contractuel),
    pas par media_users.
    """
    row = db.query_one(
        "SELECT expiration_date FROM vodum_users WHERE id = ?",
        (vodum_user_id,),
    )
    if not row:
        return False

    # Déjà une date → on ne touche pas
    if row["expiration_date"]:
        return False

    settings = db.query_one("SELECT default_subscription_days FROM settings WHERE id = 1")
    try:
        days = int(settings["default_subscription_days"]) if settings else 0
    except Exception:
        days = 0


    if days <= 0:
        return False

    today = datetime.utcnow().date()
    expiration = (today + timedelta(days=days)).isoformat()

    db.execute(
        "UPDATE vodum_users SET expiration_date = ? WHERE id = ?",
        (expiration, vodum_user_id),
    )

    logger.info(
        f"[SUBSCRIPTION] expiration_date initialisée pour vodum_user_id={vodum_user_id} → {expiration}"
    )
    return True

def _extract_joined_at(detail: Dict[str, Any]) -> Optional[str]:
    """
    Jellyfin ne fournit pas toujours une date de création dans UserDto selon versions/config.
    On tente plusieurs champs courants ; sinon None.
    """
    for key in ("DateCreated", "CreatedDate", "CreatedAt", "CreationDate", "DateCreatedUtc"):
        val = detail.get(key)
        if val:
            return str(val)
    return None


def _extract_role_from_policy(policy: Dict[str, Any]) -> Optional[str]:
    """
    Rôle simple, adapté à ton champ `media_users.role` :
    - admin si IsAdministrator
    - user sinon
    Tu peux étendre ensuite (disabled/hidden/etc).
    """
    if not isinstance(policy, dict):
        return None
    if policy.get("IsAdministrator"):
        return "admin"
    return "user"


def _extract_avatar_path(jellyfin_user_id: str, detail: Dict[str, Any]) -> Optional[str]:
    """
    On stocke une URL *relative* (sans api_key) : le front pourra l’appeler avec l’auth habituelle.
    PrimaryImageTag existe dans UserDto. :contentReference[oaicite:1]{index=1}
    """
    tag = detail.get("PrimaryImageTag")
    if not tag:
        return None
    # Route généralement supportée : /Users/{id}/Images/Primary
    # On met tag pour cache-busting.
    return f"/Users/{jellyfin_user_id}/Images/Primary?tag={tag}"


def _store_full_user_json_and_fields(
    db,
    media_user_id: int,
    jellyfin_user_id: str,
    detail: Dict[str, Any],
):
    """
    Stocke :
      - raw_json = JSON complet renvoyé par Jellyfin (/Users/{id})
      - role (admin/user)
      - joined_at (si dispo)
      - avatar (optionnel)
    """
    if not isinstance(detail, dict):
        detail = {}

    policy = detail.get("Policy") if isinstance(detail.get("Policy"), dict) else {}
    role = _extract_role_from_policy(policy)
    joined_at = _extract_joined_at(detail)
    avatar = _extract_avatar_path(jellyfin_user_id, detail)

    db.execute(
        """
        UPDATE media_users
        SET raw_json = ?,
            role = COALESCE(?, role),
            joined_at = COALESCE(?, joined_at),
            avatar = COALESCE(?, avatar)
        WHERE id = ?
        """,
        (
            json.dumps(detail, ensure_ascii=False),
            role,
            joined_at,
            avatar,
            media_user_id,
        ),
    )


# ----------------------------
# Jellyfin API helpers
# ----------------------------

def _build_api_url(base_url: str, path: str, token: str) -> str:
    base_url = (base_url or "").rstrip("/")
    path = "/" + (path or "").lstrip("/")
    return f"{base_url}{path}?api_key={token}"


def _get_json(session: requests.Session, url: str, timeout: int = 20) -> Any:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ----------------------------
# DB helpers (DB v2)
# ----------------------------

def _get_jellyfin_servers(db):
    return db.query(
        "SELECT id, name, url, token FROM servers WHERE type = 'jellyfin'"
    )


def _ensure_vodum_user_for_username(
    db,
    username: str,
    *,
    provider_type: Optional[str] = None,
    server_id: Optional[int] = None,
    external_user_id: Optional[str] = None,
) -> int:
    """
    Assure l'existence d'un vodum_user.

    - Pour Jellyfin (et tout provider server-scoped) :
      on DOIT utiliser une identité (type, server_id, external_user_id) via user_identities,
      car un même username peut exister sur plusieurs serveurs.

    - Fallback legacy :
      si provider_type/server_id/external_user_id ne sont pas fournis,
      on garde le comportement historique basé sur username.
    """

    # --- Mode identity-first (recommandé pour Jellyfin) ---
    if provider_type and server_id is not None and external_user_id:
        row = db.query_one(
            """
            SELECT vodum_user_id
            FROM user_identities
            WHERE type = ?
              AND server_id = ?
              AND external_user_id = ?
            LIMIT 1
            """,
            (provider_type, int(server_id), str(external_user_id)),
        )
        if row and row.get("vodum_user_id"):
            return int(row["vodum_user_id"])

        # Crée un vodum_user placeholder
        cur = db.execute(
            "INSERT INTO vodum_users (username, status) VALUES (?, 'active')",
            (username,),
        )
        vodum_user_id = int(cur.lastrowid)

        # Crée l'identité liée (clé unique)
        db.execute(
            """
            INSERT INTO user_identities (vodum_user_id, type, server_id, external_user_id)
            VALUES (?, ?, ?, ?)
            """,
            (vodum_user_id, provider_type, int(server_id), str(external_user_id)),
        )

        return vodum_user_id

    # --- Fallback legacy (username only) ---
    row = db.query_one(
        "SELECT id FROM vodum_users WHERE username = ? LIMIT 1",
        (username,),
    )
    if row:
        return int(row["id"])

    cur = db.execute(
        "INSERT INTO vodum_users (username, status) VALUES (?, 'active')",
        (username,),
    )
    return int(cur.lastrowid)


def _upsert_media_user_by_jellyfin_id(
    db,
    server_id: int,
    jellyfin_id: str,
    username: str,
) -> Tuple[int, int]:
    """
    Upsert d'un compte Jellyfin dans media_users.

    Retourne (media_user_id, vodum_user_id)
    """
    # 1) Cherche un compte existant sur CE serveur
    row = db.query_one(
        """
        SELECT id, vodum_user_id
        FROM media_users
        WHERE server_id = ?
          AND type = 'jellyfin'
          AND external_user_id = ?
        LIMIT 1
        """,
        (server_id, jellyfin_id),
    )

    # 2) Assure un vodum_user
    if row and row["vodum_user_id"]:
        vodum_user_id = int(row["vodum_user_id"])
    else:
        vodum_user_id = _ensure_vodum_user_for_username(
            db,
            username,
            provider_type="jellyfin",
            server_id=server_id,
            external_user_id=jellyfin_id,
        )
        db.execute(
            """
            INSERT OR IGNORE INTO user_identities (vodum_user_id, type, server_id, external_user_id)
            VALUES (?, 'jellyfin', ?, ?)
            """,
            (vodum_user_id, server_id, jellyfin_id),
        )


    if row:
        media_user_id = int(row["id"])
        db.execute(
            """
            UPDATE media_users
            SET username = ?,
                vodum_user_id = COALESCE(vodum_user_id, ?)
            WHERE id = ?
            """,
            (username, vodum_user_id, media_user_id),
        )
        return media_user_id, vodum_user_id

    # 3) Insert nouveau media_user
    cur = db.execute(
        """
        INSERT INTO media_users (server_id, vodum_user_id, external_user_id, username, type)
        VALUES (?, ?, ?, ?, 'jellyfin')
        """,
        (server_id, vodum_user_id, jellyfin_id, username),
    )
    return int(cur.lastrowid), vodum_user_id


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


def _set_media_user_state(
    db,
    media_user_id: int,
    server_id: int,
    owned: int,
    all_libraries: int,
    num_libraries: int,
    last_seen_at: Optional[str],
):
    """
    Anciennement: user_servers (DB v1).
    DB v2: on stocke l'état dans media_users.details_json pour garder l'info,
    sans recréer une table user_servers.
    """
    details = {
        "owned": int(owned),
        "all_libraries": int(all_libraries),
        "num_libraries": int(num_libraries),
        "pending": 0,
        "last_seen_at": last_seen_at,
        "source": "jellyfin_api",
        "server_id": int(server_id),
    }

    db.execute(
        "UPDATE media_users SET details_json = ? WHERE id = ?",
        (json.dumps(details, ensure_ascii=False), media_user_id),
    )


def _refresh_shared_libraries_for_server(
    db,
    media_user_id: int,
    server_id: int,
    allowed_library_ids: List[int],
):
    """
    Anciennement: shared_libraries (DB v1).
    DB v2: media_user_libraries.
    """
    db.execute(
        """
        DELETE FROM media_user_libraries
        WHERE media_user_id = ?
          AND library_id IN (
              SELECT id FROM libraries WHERE server_id = ?
          )
        """,
        (media_user_id, server_id),
    )

    for lib_id in allowed_library_ids:
        db.execute(
            """
            INSERT OR IGNORE INTO media_user_libraries (media_user_id, library_id)
            VALUES (?, ?)
            """,
            (media_user_id, lib_id),
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

    if not isinstance(data, list):
        return mapping

    for entry in data:
        if not isinstance(entry, dict):
            continue

        item_id = entry.get("ItemId")
        name = entry.get("Name") or ""
        lib_type = entry.get("CollectionType") or entry.get("Type") or ""

        if not item_id or not name:
            continue

        lib_db_id = _upsert_library(db, server_id, str(item_id), str(name), str(lib_type))
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
    - Récupère tous les users Jellyfin
    - Pour chacun, récupère /Users/{id} pour Policy
    - Met à jour media_users + media_user_libraries (DB v2)
    """
    users_url = _build_api_url(url, "/Users", token)
    logger.info(f"Jellyfin users: GET {users_url}")

    users = _get_json(session, users_url, timeout=30) or []
    processed = 0
    policy_ok = 0

    if not isinstance(users, list):
        return 0, 0

    for u in users:
        if not isinstance(u, dict):
            continue

        jellyfin_id = u.get("Id")
        username = u.get("Name")
        if not jellyfin_id or not username:
            continue

        jellyfin_id = str(jellyfin_id)
        username = str(username)

        media_user_id, vodum_user_id = _upsert_media_user_by_jellyfin_id(
            db, server_id, jellyfin_id, username
        )

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

        # Stockage "max info" : JSON brut + champs utiles (role/joined_at/avatar)
        try:
            if isinstance(detail, dict):
                _store_full_user_json_and_fields(db, media_user_id, jellyfin_id, detail)
        except Exception as e:
            logger.warning(
                f"Impossible de stocker raw_json/role/joined_at pour user={username} ({jellyfin_id}) "
                f"sur server_id={server_id}: {e}"
            )


        policy = (
            (detail.get("Policy") or u.get("Policy") or {})
            if isinstance(detail, dict)
            else {}
        )

        enable_all = 1 if policy.get("EnableAllFolders") else 0
        enabled_folders = policy.get("EnabledFolders") or []

        # last activity info (si présent)
        last_seen_at = None
        if isinstance(detail, dict):
            last_seen_at = (
                detail.get("LastActivityDate")
                or detail.get("LastLoginDate")
                or None
            )

        # Calcul libraries autorisées
        allowed_db_lib_ids: List[int] = []
        if enable_all:
            allowed_db_lib_ids = list(lib_map_itemid_to_dbid.values())
        else:
            if isinstance(enabled_folders, list):
                for folder_id in enabled_folders:
                    if not folder_id:
                        continue
                    lib_db_id = lib_map_itemid_to_dbid.get(str(folder_id))
                    if lib_db_id:
                        allowed_db_lib_ids.append(lib_db_id)

        _set_media_user_state(
            db,
            media_user_id=media_user_id,
            server_id=server_id,
            owned=0,
            all_libraries=enable_all,
            num_libraries=len(allowed_db_lib_ids),
            last_seen_at=last_seen_at,
        )

        _refresh_shared_libraries_for_server(
            db, media_user_id, server_id, allowed_db_lib_ids
        )

        # Si accès réel → init expiration_date sur le vodum_user
        if allowed_db_lib_ids:
            ensure_expiration_date_on_first_access(db, vodum_user_id)

        processed += 1

    logger.info(
        f"Jellyfin users/policies: {processed} users traités, "
        f"policy récupérée pour {policy_ok} users (server_id={server_id})"
    )
    return processed, policy_ok


# ----------------------------
# Public task entrypoint
# ----------------------------

def run(task_id: int, db):
    """
    Synchronisation complète Jellyfin (lecture seule côté Jellyfin)
    - Users (media_users)
    - Libraries (libraries)
    - Policies → media_user_libraries
    """
    logger.info("=== SYNC JELLYFIN : START ===")

    servers = _get_jellyfin_servers(db)
    if not servers:
        logger.warning("Aucun serveur Jellyfin en base.")
        logger.info("=== SYNC JELLYFIN : END ===")
        return

    total_users = 0
    total_policy_ok = 0
    total_libraries = 0

    session = requests.Session()

    try:
        any_success = False

        for srv in servers:
            srv = dict(srv)
            server_id = int(srv["id"])
            name = srv.get("name") or f"server_{server_id}"
            url = (srv.get("url") or "").strip()
            token = (srv.get("token") or "").strip()

            if not url or not token:
                logger.warning(f"[SYNC JELLYFIN] serveur {name} (id={server_id}) URL/TOKEN manquant")
                continue

            try:
                lib_map = _sync_libraries_for_server(session, db, server_id, url, token)
                total_libraries += len(lib_map)

                users_count, policy_ok = _sync_users_and_policies_for_server(
                    session, db, server_id, url, token, lib_map
                )
                total_users += users_count
                total_policy_ok += policy_ok

                any_success = True
                logger.info(f"[SYNC JELLYFIN] OK server={name} (users={users_count}, libs={len(lib_map)})")

            except Exception as e:
                logger.error(
                    f"[SYNC JELLYFIN] Connexion ou synchronisation impossible pour {name} : {e}",
                    exc_info=True,
                )
                continue

        if not any_success:
            raise RuntimeError("Aucun serveur Jellyfin n'a pu être synchronisé")

        logger.info(f"Sync Jellyfin OK — users={total_users}, libraries={total_libraries}")

    except Exception:
        logger.error("Erreur globale sync_jellyfin", exc_info=True)
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
