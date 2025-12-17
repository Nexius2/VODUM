
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Tuple, Optional

import requests
import xml.etree.ElementTree as ET

from logging_utils import get_logger
from tasks_engine import task_logs
from plexapi.server import PlexServer  



# ---------------------------------------------------------------------------
# CONFIG & LOGGER
# ---------------------------------------------------------------------------


log = get_logger("sync_plex")


def ensure_expiration_date_on_first_access(db, user_id):
    """
    Initialise expiration_date UNIQUEMENT si :
      - expiration_date est NULL
      - default_subscription_days > 0
    """
    row = db.query_one(
        "SELECT expiration_date FROM users WHERE id = ?",
        (user_id,)
    )

    if not row or row["expiration_date"] is not None:
        return False

    row = db.query_one(
        "SELECT default_subscription_days FROM settings LIMIT 1"
    )

    try:
        days = int(row["default_subscription_days"]) if row else 0
    except Exception:
        days = 0

    if days <= 0:
        return False

    today = datetime.utcnow().date()
    expiration = (today + timedelta(days=days)).isoformat()

    db.execute(
        "UPDATE users SET expiration_date = ? WHERE id = ?",
        (expiration, user_id)
    )

    log.info(
        f"[SUBSCRIPTION] expiration_date initialisée pour user_id={user_id} → {expiration}"
    )
    return True



# ---------------------------------------------------------------------------
# Token Plex.tv (pris dans la table servers)
# ---------------------------------------------------------------------------
def choose_account_token(db) -> Optional[str]:
    """
    Retourne un token Plex (account) trouvé dans la table 'servers'.
    On prend le premier serveur Plex avec un token non vide.
    """
    row = db.query_one(
        """
        SELECT token
        FROM servers
        WHERE type='plex'
          AND token IS NOT NULL
          AND token != ''
        LIMIT 1
        """
    )

    if not row:
        log.error("[SYNC USERS] Aucun token Plex trouvé dans la table 'servers'.")
        return None

    token = row["token"]
    if not token:
        log.error("[SYNC USERS] Token vide dans la table 'servers'.")
        return None

    return token




# ---------------------------------------------------------------------------
# Récupération Libraries Plex (JSON local API)
# ---------------------------------------------------------------------------






def plex_get_user_access(plex, server_name, user_email):
    """
    Retourne les libraries réellement partagées avec un user donné.
    Utilise la méthode fiable démontrée dans plex_backup.py.
    """
    account = plex.myPlexAccount()

    try:
        user_acct = account.user(user_email)
    except Exception as e:
        log.error(f"[ACCESS] Impossible d'obtenir les infos pour {user_email}: {e}")
        return []

    out = []

    for srv in user_acct.servers:
        if srv.name != server_name:
            continue

        try:
            for section in srv.sections():
                if getattr(section, "shared", False) is True:
                    out.append({
                        "title": section.title,
                        "key": str(section.key)
                    })
        except Exception as e:
            log.error(f"[ACCESS] Erreur en parcourant sections user {user_email}: {e}")

    return out


def sync_plex_user_library_access(db, plex, server):
    """
    Synchronise l'accès réel (shared_libraries) pour un serveur Plex donné,
    en se basant sur PlexAPI (plex_get_user_access).

    - DBManager only (query/query_one/execute)
    - Aucun commit/rollback/close ici
    - Déclenche l'initialisation expiration_date si l'user a au moins 1 accès
    """
    server_id = server["id"]
    server_name = server["name"]

    # ----------------------------------------------------
    # 1) Mapping libraries du serveur : section_id -> library_id (DB)
    # ----------------------------------------------------
    libraries = db.query(
        "SELECT id, section_id FROM libraries WHERE server_id = ?",
        (server_id,),
    )
    lib_map = {str(row["section_id"]): row["id"] for row in libraries}

    if not lib_map:
        log.warning(f"[SYNC ACCESS] Aucune library en base pour server={server_name} (id={server_id})")
        return

    # ----------------------------------------------------
    # 2) Users liés à ce serveur (via user_servers)
    # ----------------------------------------------------
    users = db.query(
        """
        SELECT u.email, u.id AS user_id
        FROM users u
        JOIN user_servers us ON us.user_id = u.id
        WHERE us.server_id = ?
        """,
        (server_id,),
    )

    if not users:
        log.info(f"[SYNC ACCESS] Aucun user lié à server={server_name} (id={server_id})")
        return

    updated_users = 0

    # ----------------------------------------------------
    # 3) Pour chaque user : on resync shared_libraries sur CE serveur
    # ----------------------------------------------------
    for u in users:
        email = u["email"]
        user_id = u["user_id"]

        # Nettoyer les anciens accès pour CE serveur
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

        if not email:
            continue

        # Données réelles côté Plex
        access = plex_get_user_access(plex, server_name, email)

        has_access = False
        for entry in access:
            sec_id = str(entry.get("key") or "")
            if not sec_id:
                continue

            lib_id = lib_map.get(sec_id)
            if not lib_id:
                continue

            db.execute(
                """
                INSERT OR IGNORE INTO shared_libraries(user_id, library_id)
                VALUES (?, ?)
                """,
                (user_id, lib_id),
            )
            has_access = True

        # Déclencheur abonnement
        if has_access:
            ensure_expiration_date_on_first_access(db, user_id)

        updated_users += 1

    log.info(f"[SYNC ACCESS] Accès mis à jour pour serveur {server_name} (users traités={updated_users})")




def plex_get_libraries(server):
    """
    Récupère la liste des libraries d’un serveur Plex.
    Retourne :
    [
        {"section_id": "1", "name": "Films", "type": "movie"},
        ...
    ]
    """
    base_url = server["url"] or server["local_url"]
    token = server["token"]

    if not base_url or not token:
        log.error(f"[SYNC LIBRARIES] Serveur {server['name']} sans URL ou token.")
        return []

    url = f"{base_url}/library/sections"
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"[SYNC LIBRARIES] Erreur API {url}: {e}")
        return []

    data = resp.json()
    libs = data.get("MediaContainer", {}).get("Directory", [])
    out = []

    for item in libs:
        out.append({
            "section_id": str(item.get("key")),
            "name": item.get("title"),
            "type": item.get("type", "unknown")
        })

    log.info(f"[SYNC LIBRARIES] {len(out)} libraries détectées sur {server['name']}")
    return out

def sync_plex_libraries(db, server, libraries):
    """
    Synchronise les libraries Plex pour un serveur donné.
    """
    server_id = server["id"]

    rows = db.query(
        "SELECT id, section_id FROM libraries WHERE server_id = ?",
        (server_id,),
    )

    existing = {row["section_id"]: row["id"] for row in rows}
    found = set()

    for lib in libraries:
        sid = lib["section_id"]
        found.add(sid)

        if sid in existing:
            db.execute(
                """
                UPDATE libraries
                SET name = ?, type = ?
                WHERE id = ?
                """,
                (lib["name"], lib["type"], existing[sid]),
            )
        else:
            db.execute(
                """
                INSERT INTO libraries(server_id, section_id, name, type)
                VALUES (?, ?, ?, ?)
                """,
                (server_id, sid, lib["name"], lib["type"]),
            )

    for sid, lib_id in existing.items():
        if sid not in found:
            log.info(f"[SYNC LIBRARIES] Suppression library {lib_id} (section={sid})")
            db.execute("DELETE FROM shared_libraries WHERE library_id = ?", (lib_id,))
            db.execute("DELETE FROM libraries WHERE id = ?", (lib_id,))


  






# ---------------------------------------------------------------------------
# Appels API Plex.tv
# ---------------------------------------------------------------------------

def fetch_xml(url: str, token: str) -> Optional[ET.Element]:
    """
    GET sur url (Plex.tv), retourne root XML ou None en cas d'erreur.
    """
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/xml",
        "X-Plex-Client-Identifier": "vodum-sync-plex",
    }

    log.debug(f"[API] GET {url}")

    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except Exception as e:
        log.error(f"[API] Erreur réseau sur {url}: {e}")
        return None

    if resp.status_code != 200:
        log.error(f"[API] {url} → HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        root = ET.fromstring(resp.content)
        return root
    except Exception as e:
        log.error(f"[API] XML invalide pour {url}: {e}")
        return None


def fetch_users_from_plex_api(token: str, db=None) -> Dict[str, Dict[str, Any]]:
    """
    Appelle Plex.tv /api/users et renvoie un dict :
      {
        plex_id: {
            ... infos user ...,
            "servers": [ {...}, ... ]
        }
      }
    """
    url = "https://plex.tv/api/users"
    root = fetch_xml(url, token)

    if root is None:
        log.error("[API] Impossible de récupérer /api/users → abandon.")
        return {}

    # ----------------------------------------------------
    # Email admin (pour déterminer le rôle owner)
    # ----------------------------------------------------
    admin_email = None
    if db is not None:
        row = db.query_one("SELECT admin_email FROM settings LIMIT 1")
        if row:
            admin_email = (row["admin_email"] or "").strip().lower() or None

    log.info("[API] /api/users récupéré, parsing…")

    users: Dict[str, Dict[str, Any]] = {}

    for u in root.findall("User"):
        plex_id = u.get("id")
        if not plex_id:
            continue

        plex_id = str(plex_id)

        # ------------------------
        # Champs de base
        # ------------------------
        username = u.get("username") or u.get("title") or f"user_{plex_id}"
        email = (u.get("email") or "").strip()
        avatar = u.get("thumb")

        home_flag = 1 if u.get("home") == "1" else 0
        protected_flag = 1 if u.get("protected") == "1" else 0
        restricted_flag = 1 if u.get("restricted") == "1" else 0

        allow_sync = 1 if u.get("allowSync") == "1" else 0
        allow_cam = 1 if u.get("allowCameraUpload") == "1" else 0
        allow_channels = 1 if u.get("allowChannels") == "1" else 0

        filter_all = u.get("filterAll")
        filter_movies = u.get("filterMovies")
        filter_tv = u.get("filterTelevision")
        filter_music = u.get("filterMusic")
        filter_photos = u.get("filterPhotos")
        reco_playlist_id = u.get("recommendationsPlaylistId")

        joined_at = u.get("joinedAt")
        accepted_at = u.get("acceptedAt")

        # ------------------------
        # Subscription
        # ------------------------
        sub_node = u.find("subscription")
        subscription_active = None
        subscription_status = None
        subscription_plan = None

        if sub_node is not None:
            subscription_active = sub_node.get("active")
            subscription_status = sub_node.get("status")
            subscription_plan = sub_node.get("plan")

        # ------------------------
        # Rôle Plex
        # ------------------------
        email_lower = email.lower() if email else ""

        if admin_email and email_lower == admin_email:
            plex_role = "owner"
        elif home_flag:
            plex_role = "home"
        else:
            plex_role = "friend"

        # ------------------------
        # Serveurs liés
        # ------------------------
        servers: List[Dict[str, Any]] = []

        for s in u.findall("Server"):
            servers.append({
                "machineIdentifier": s.get("machineIdentifier"),
                "name": s.get("name"),
                "home": 1 if s.get("home") == "1" else 0,
                "owned": 1 if s.get("owned") == "1" else 0,
                "allLibraries": 1 if s.get("allLibraries") == "1" else 0,
                "numLibraries": int(s.get("numLibraries") or 0),
                "lastSeenAt": s.get("lastSeenAt"),
                "pending": 1 if s.get("pending") == "1" else 0,
            })

        users[plex_id] = {
            "plex_id": plex_id,
            "username": username,
            "email": email,
            "avatar": avatar,
            "plex_role": plex_role,

            "home": home_flag,
            "protected": protected_flag,
            "restricted": restricted_flag,

            "allow_sync": allow_sync,
            "allow_camera_upload": allow_cam,
            "allow_channels": allow_channels,

            "filter_all": filter_all,
            "filter_movies": filter_movies,
            "filter_television": filter_tv,
            "filter_music": filter_music,
            "filter_photos": filter_photos,

            "recommendations_playlist_id": reco_playlist_id,

            "joined_at": joined_at,
            "accepted_at": accepted_at,

            "subscription_active": subscription_active,
            "subscription_status": subscription_status,
            "subscription_plan": subscription_plan,

            "servers": servers,
        }

        log.debug(
            f"[API] User plex_id={plex_id} username={username!r} "
            f"role={plex_role}, servers={len(servers)}"
        )

    log.info(f"[API] /api/users → {len(users)} utilisateur(s) récupéré(s).")
    return users



# ---------------------------------------------------------------------------
# Sync USERS + user_servers (à partir de /api/users)
# ---------------------------------------------------------------------------

def sync_users_from_api(db) -> None:
    """
    Synchronise les utilisateurs Plex à partir de l'API Plex.tv (/api/users)

    - Upsert table users
    - Upsert table user_servers (source = plex_api)
    - Nettoie les liens user_servers obsolètes
    - NE fait AUCUN commit / rollback / close
    """
    log.info("=== [SYNC USERS] Début synchronisation utilisateurs Plex (API Plex.tv) ===")

    # ----------------------------------------------------
    # 1) Token Plex.tv
    # ----------------------------------------------------
    token = choose_account_token(db)
    if not token:
        raise RuntimeError("[SYNC USERS] Aucun token Plex disponible")


    # ----------------------------------------------------
    # 2) Appel API Plex.tv
    # ----------------------------------------------------
    users_data = fetch_users_from_plex_api(token, db=db)
    if not users_data:
        raise RuntimeError("[SYNC USERS] Aucun utilisateur renvoyé par Plex.tv")


    # ----------------------------------------------------
    # 3) Mapping serveurs Plex (machineIdentifier → id)
    # ----------------------------------------------------
    rows = db.query(
        "SELECT id, server_identifier FROM servers WHERE type='plex'"
    )

    server_id_by_machine = {
        r["server_identifier"]: r["id"]
        for r in rows
        if r["server_identifier"]
    }

    log.info(
        f"[SYNC USERS] Serveurs Plex connus : {len(server_id_by_machine)}"
    )

    today = datetime.utcnow().date()
    seen_plex_ids: Set[str] = set()
    seen_user_servers: Set[Tuple[int, int]] = set()

    # ----------------------------------------------------
    # 4) Upsert USERS + user_servers
    # ----------------------------------------------------
    for plex_id, data in users_data.items():
        seen_plex_ids.add(plex_id)

        username = data["username"]
        email = data["email"]
        avatar = data["avatar"]
        plex_role = data["plex_role"]

        home_flag = data.get("home", 0)
        protected_flag = data.get("protected", 0)
        restricted_flag = data.get("restricted", 0)

        joined_at = data.get("joined_at")
        accepted_at = data.get("accepted_at")

        subscription_active = data.get("subscription_active")
        subscription_status = data.get("subscription_status")
        subscription_plan = data.get("subscription_plan")

        # ------------------------------------------------
        # USERS : SELECT
        # ------------------------------------------------
        row = db.query_one(
            "SELECT id FROM users WHERE plex_id = ?",
            (plex_id,)
        )

        # ------------------------------------------------
        # UPDATE EXISTANT
        # ------------------------------------------------
        if row:
            user_id = row["id"]

            db.execute(
                """
                UPDATE users
                SET username            = ?,
                    email               = ?,
                    avatar              = ?,
                    plex_role           = ?,
                    home                = ?,
                    protected           = ?,
                    restricted          = ?,
                    joined_at           = ?,
                    accepted_at         = ?,
                    subscription_active = ?,
                    subscription_status = ?,
                    subscription_plan   = ?
                WHERE id = ?
                """,
                (
                    username,
                    email,
                    avatar,
                    plex_role or "unknown",
                    home_flag,
                    protected_flag,
                    restricted_flag,
                    joined_at,
                    accepted_at,
                    subscription_active,
                    subscription_status,
                    subscription_plan,
                    user_id,
                ),
            )

        # ------------------------------------------------
        # INSERT NOUVEAU
        # ------------------------------------------------
        else:
            cur = db.execute(
                """
                INSERT INTO users(
                    plex_id, username, email, avatar, plex_role,
                    home, protected, restricted,
                    joined_at, accepted_at,
                    subscription_active, subscription_status, subscription_plan,
                    creation_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plex_id,
                    username,
                    email,
                    avatar,
                    plex_role or "unknown",
                    home_flag,
                    protected_flag,
                    restricted_flag,
                    joined_at,
                    accepted_at,
                    subscription_active,
                    subscription_status,
                    subscription_plan,
                    today.isoformat(),
                ),
            )
            user_id = cur.lastrowid
            log.info(f"[SYNC USERS] Nouvel utilisateur créé user_id={user_id} plex_id={plex_id}")

        # ------------------------------------------------
        # USER_SERVERS
        # ------------------------------------------------
        for srv in data.get("servers", []):
            machine_id = srv.get("machineIdentifier")
            if not machine_id:
                continue

            server_id = server_id_by_machine.get(machine_id)
            if not server_id:
                continue

            seen_user_servers.add((user_id, server_id))

            db.execute(
                """
                INSERT INTO user_servers(
                    user_id, server_id,
                    owned, all_libraries, num_libraries, pending, last_seen_at,

                    allow_sync, allow_camera_upload, allow_channels,
                    allow_tuners, allow_subtitle_admin,

                    filter_all, filter_movies, filter_music,
                    filter_photos, filter_television,
                    recommendations_playlist_id,

                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'plex_api')
                ON CONFLICT(user_id, server_id) DO UPDATE SET
                    owned                       = excluded.owned,
                    all_libraries               = excluded.all_libraries,
                    num_libraries               = excluded.num_libraries,
                    pending                     = excluded.pending,
                    last_seen_at                = excluded.last_seen_at,

                    allow_sync                  = excluded.allow_sync,
                    allow_camera_upload         = excluded.allow_camera_upload,
                    allow_channels              = excluded.allow_channels,
                    allow_tuners                = excluded.allow_tuners,
                    allow_subtitle_admin        = excluded.allow_subtitle_admin,

                    filter_all                  = excluded.filter_all,
                    filter_movies               = excluded.filter_movies,
                    filter_music                = excluded.filter_music,
                    filter_photos               = excluded.filter_photos,
                    filter_television           = excluded.filter_television,
                    recommendations_playlist_id = excluded.recommendations_playlist_id,

                    source = 'plex_api'
                """,
                (
                    user_id,
                    server_id,
                    srv.get("owned", 0),
                    srv.get("allLibraries", 0),
                    srv.get("numLibraries", 0),
                    srv.get("pending", 0),
                    srv.get("lastSeenAt"),

                    data.get("allow_sync", 0),
                    data.get("allow_camera_upload", 0),
                    data.get("allow_channels", 0),
                    0,  # allow_tuners (non exposé par Plex.tv)
                    0,  # allow_subtitle_admin (non exposé par Plex.tv)

                    data.get("filter_all"),
                    data.get("filter_movies"),
                    data.get("filter_music"),
                    data.get("filter_photos"),
                    data.get("filter_television"),
                    data.get("recommendations_playlist_id"),
                ),
            )

    # ----------------------------------------------------
    # 5) Nettoyage user_servers obsolètes (plex_api)
    # ----------------------------------------------------
    rows = db.query(
        """
        SELECT us.user_id, us.server_id
        FROM user_servers us
        JOIN servers s ON s.id = us.server_id
        WHERE us.source = 'plex_api'
          AND s.type    = 'plex'
        """
    )

    removed = 0
    for r in rows:
        key = (r["user_id"], r["server_id"])
        if key not in seen_user_servers:
            db.execute(
                """
                DELETE FROM user_servers
                WHERE user_id = ? AND server_id = ? AND source = 'plex_api'
                """,
                (r["user_id"], r["server_id"]),
            )
            removed += 1

    log.info(
        f"=== [SYNC USERS] Fin sync Plex.tv : users={len(seen_plex_ids)}, "
        f"liens actifs={len(seen_user_servers)}, liens supprimés={removed} ==="
    )



# ---------------------------------------------------------------------------
# SYNC GLOBALE (pour compat avec l'ancien sync_all)
# ---------------------------------------------------------------------------

def sync_all(task_id=None, db=None) -> None:
    """
    Synchronisation complète Plex :
      - users / user_servers via Plex.tv
      - libraries via API locale
      - accès users → libraries via PlexAPI

    DBManager ONLY :
      - aucune ouverture / fermeture DB
      - aucun commit
    """
    if db is None:
        raise RuntimeError("sync_all() doit recevoir un DBManager")

    log.info("=== [SYNC ALL] Début synchronisation Plex ===")

    # -------------------------------------------------
    # 1) Users + user_servers (API Plex.tv)
    # -------------------------------------------------
    sync_users_from_api(db)

    # -------------------------------------------------
    # 2) Serveurs Plex
    # -------------------------------------------------
    servers = db.query("SELECT * FROM servers WHERE type='plex'")

    if not servers:
        raise RuntimeError("Aucun serveur Plex trouvé en base")

    any_success = False

    for server in servers:
        server_name = server["name"]
        log.info(f"[SYNC ALL] Serveur Plex : {server_name}")

        # --- Libraries ---
        try:
            libs = plex_get_libraries(server)
            sync_plex_libraries(db, server, libs)
        except Exception as e:
            log.error(
                f"[SYNC LIBS] Erreur synchronisation bibliothèques pour {server_name}: {e}",
                exc_info=True
            )
            continue

        # --- Accès utilisateurs ---
        base_url = server["url"] or server["local_url"]
        token = server["token"]

        if not base_url or not token:
            log.warning(
                f"[SYNC ACCESS] Serveur {server_name} sans URL/token → accès ignoré"
            )
            continue

        try:
            plex = PlexServer(base_url, token)
            sync_plex_user_library_access(db, plex, server)
            any_success = True

        except Exception as e:
            log.error(
                f"[SYNC ACCESS] Connexion ou synchronisation impossible pour {server_name}: {e}",
                exc_info=True
            )
            continue

    if not any_success:
        raise RuntimeError("Aucun serveur Plex n'a pu être synchronisé")

    log.info("=== [SYNC ALL] Synchronisation Plex terminée ===")



# ---------------------------------------------------------------------------
# API POUR LE SCHEDULER (tasks_engine)
# ---------------------------------------------------------------------------

def run(task_id: int, db):
    """
    Point d'entrée pour le scheduler VODUM.
    """

    log.info("=== [SYNC_PLEX] Tâche sync_plex démarrée ===")
    log.debug(f"[SYNC_PLEX] task_id={task_id}")

    task_logs(task_id, "info", "Synchronisation Plex démarrée…")

    start = time.monotonic()

    try:
        sync_all(task_id, db=db)

        duration = time.monotonic() - start
        log.info(f"=== [SYNC_PLEX] Terminé OK en {duration:.2f}s ===")

        if db.query_one("SELECT 1 FROM users LIMIT 1"):
            task_logs(task_id, "success", "Synchronisation Plex terminée avec succès.")
        else:
            task_logs(task_id, "info", "Synchronisation Plex terminée — aucun utilisateur trouvé.")

    except Exception as e:
        duration = time.monotonic() - start
        log.error(
            f"=== [SYNC_PLEX] ÉCHEC après {duration:.2f}s ===",
            exc_info=True,
        )
        task_logs(task_id, "error", f"Erreur pendant sync_plex : {e}")
        raise


