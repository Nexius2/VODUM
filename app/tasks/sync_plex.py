import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Tuple, Optional

import requests
import xml.etree.ElementTree as ET

from config import Config
from db_utils import open_db
from logging_utils import get_logger
from tasks_engine import task_logs

# ---------------------------------------------------------------------------
# CONFIG & LOGGER
# ---------------------------------------------------------------------------

DB_PATH = getattr(Config, "DATABASE", "/appdata/database.db")
log = get_logger("sync_plex")


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = open_db()
    conn.row_factory = sqlite3.Row
    return conn


def ensure_expiration_date_on_first_access(db, user_id):
    """
    Initialise expiration_date UNIQUEMENT si :
      - expiration_date est NULL
      - default_subscription_days > 0
    """
    row = db.execute(
        "SELECT expiration_date FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not row or row["expiration_date"] is not None:
        return False  # déjà définie ou user absent

    row = db.execute(
        "SELECT default_subscription_days FROM settings LIMIT 1"
    ).fetchone()

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

def choose_account_token(db: sqlite3.Connection) -> Optional[str]:
    """
    Retourne un token Plex (account) trouvé dans la table 'servers'.
    On prend le premier serveur Plex avec un token non vide.
    """
    row = db.execute(
        """
        SELECT token
        FROM servers
        WHERE type='plex'
          AND token IS NOT NULL
          AND token != ''
        LIMIT 1
        """
    ).fetchone()

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




from plexapi.server import PlexServer  

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
    server_id = server["id"]
    server_name = server["name"]

    # maps des libraries du serveur
    libraries = db.execute(
        "SELECT id, section_id FROM libraries WHERE server_id = ?", (server_id,)
    ).fetchall()

    lib_map = {row["section_id"]: row["id"] for row in libraries}

    # users liés à ce serveur
    users = db.execute("""
        SELECT u.email, u.id as user_id
        FROM users u
        JOIN user_servers us ON us.user_id = u.id
        WHERE us.server_id = ?
    """, (server_id,)).fetchall()

    for u in users:
        email = u["email"]
        user_id = u["user_id"]

        # supprimer anciens accès
        db.execute("""
            DELETE FROM shared_libraries
            WHERE user_id=? AND library_id IN (
                SELECT id FROM libraries WHERE server_id=?
            )
        """, (user_id, server_id))

        # accéder aux vraies données Plex
        access = plex_get_user_access(plex, server_name, email)
        has_access = False  # ✅ INITIALISATION 

        for entry in access:
            sec_id = entry["key"]

            if sec_id in lib_map:
                db.execute("""
                    INSERT OR IGNORE INTO shared_libraries(user_id, library_id)
                    VALUES (?, ?)
                """, (user_id, lib_map[sec_id]))
                has_access = True

        # 🔑 DÉCLENCHEUR abonnement
        if has_access:
            ensure_expiration_date_on_first_access(db, user_id)

    db.commit()
    log.info(f"[SYNC ACCESS] Accès mis à jour pour serveur {server_name}")



def plex_get_libraries(server: sqlite3.Row):
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
        resp = requests.get(url, headers=headers, timeout=10)
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
    Met à jour la table libraries :
        + ajoute nouvelles
        + met à jour existantes
        + supprime celles qui ont disparu
    Nettoie aussi shared_libraries pour les libraries supprimées.
    """
    server_id = server["id"]

    # Libraries existantes
    rows = db.execute(
        "SELECT id, section_id FROM libraries WHERE server_id = ?",
        (server_id,)
    ).fetchall()

    existing = {row["section_id"]: row["id"] for row in rows}
    found = set()

    # Ajout / Mise à jour
    for lib in libraries:
        sid = lib["section_id"]
        found.add(sid)

        if sid in existing:
            db.execute("""
                UPDATE libraries
                SET name = ?, type = ?
                WHERE id = ?
            """, (lib["name"], lib["type"], existing[sid]))
        else:
            db.execute("""
                INSERT INTO libraries(server_id, section_id, name, type)
                VALUES (?, ?, ?, ?)
            """, (server_id, sid, lib["name"], lib["type"]))

    # Suppression des libraries disparues
    for sid, lib_id in existing.items():
        if sid not in found:
            log.info(f"[SYNC LIBRARIES] Suppression library {lib_id} (section={sid})")
            db.execute("DELETE FROM shared_libraries WHERE library_id=?", (lib_id,))
            db.execute("DELETE FROM libraries WHERE id=?", (lib_id,))

    db.commit()

def sync_plex_libraries(db, server, libraries):
    """
    Met à jour la table libraries :
        + ajoute nouvelles
        + met à jour existantes
        + supprime celles qui ont disparu
    Nettoie aussi shared_libraries pour les libraries supprimées.
    """
    server_id = server["id"]

    # Libraries existantes
    rows = db.execute(
        "SELECT id, section_id FROM libraries WHERE server_id = ?",
        (server_id,)
    ).fetchall()

    existing = {row["section_id"]: row["id"] for row in rows}
    found = set()

    # Ajout / Mise à jour
    for lib in libraries:
        sid = lib["section_id"]
        found.add(sid)

        if sid in existing:
            db.execute("""
                UPDATE libraries
                SET name = ?, type = ?
                WHERE id = ?
            """, (lib["name"], lib["type"], existing[sid]))
        else:
            db.execute("""
                INSERT INTO libraries(server_id, section_id, name, type)
                VALUES (?, ?, ?, ?)
            """, (server_id, sid, lib["name"], lib["type"]))

    # Suppression des libraries disparues
    for sid, lib_id in existing.items():
        if sid not in found:
            log.info(f"[SYNC LIBRARIES] Suppression library {lib_id} (section={sid})")
            db.execute("DELETE FROM shared_libraries WHERE library_id=?", (lib_id,))
            db.execute("DELETE FROM libraries WHERE id=?", (lib_id,))

    db.commit()

def sync_user_library_access(db, server):
    """
    Assigne les accès library-level selon :
      - allLibraries = 1 → accès à toutes les libraries du serveur
      - allLibraries = 0 mais numLibraries > 0 → Plex ne fournit plus le détail →
                      on ASSIGNE toutes les libraries (comportement PlexAPI)
    """

    server_id = server["id"]

    # Récupérer toutes les libraries du serveur
    libs = db.execute(
        "SELECT id FROM libraries WHERE server_id = ?",
        (server_id,)
    ).fetchall()

    lib_ids = [l["id"] for l in libs]

    if not lib_ids:
        return

    # Récupération des users ayant accès au serveur (user_servers)
    rows = db.execute("""
        SELECT user_id, all_libraries, num_libraries
        FROM user_servers
        WHERE server_id = ?
    """, (server_id,)).fetchall()

    for row in rows:
        user_id = row["user_id"]

        # Nettoyer les accès actuels
        db.execute(
            "DELETE FROM shared_libraries WHERE user_id = ? AND library_id IN (SELECT id FROM libraries WHERE server_id = ?)",
            (user_id, server_id)
        )

        # Règle 1 : accès total ?
        if row["all_libraries"] == 1:
            for lib_id in lib_ids:
                db.execute(
                    "INSERT OR IGNORE INTO shared_libraries(user_id, library_id) VALUES (?, ?)",
                    (user_id, lib_id)
                )
            continue

        # Règle 2 : accès partiel → Plex **ne fournit plus la liste exacte**
        # Comportement standard PlexAPI :
        # → assigner toutes les libraries visibles
        if row["num_libraries"] > 0:
            for lib_id in lib_ids:
                db.execute(
                    "INSERT OR IGNORE INTO shared_libraries(user_id, library_id) VALUES (?, ?)",
                    (user_id, lib_id)
                )

    db.commit()

    log.info(f"[SYNC ACCESS] Accès libraries synchronisés pour serveur {server['name']}")



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


def fetch_users_from_plex_api(token: str, db: Optional[sqlite3.Connection] = None) -> Dict[str, Dict[str, Any]]:
    """
    Appelle Plex.tv /api/users et renvoie un dict:
      { plex_id (str): { ...infos user..., "servers": [ {machineIdentifier, name, ...}, ... ] } }

    RÔLES:
      - owner  : email == settings.admin_email
      - home   : utilisateur "home" (home="1") mais pas owner
      - friend : le reste
      - unfriended : attribué plus tard quand l'user disparaît de l'API
    """
    url = "https://plex.tv/api/users"
    root = fetch_xml(url, token)
    if root is None:
        log.error("[API] Impossible de récupérer /api/users → abandon.")
        return {}

    admin_email = None
    if db is not None:
        row = db.execute("SELECT admin_email FROM settings LIMIT 1").fetchone()
        if row:
            admin_email = (row["admin_email"] or "").strip().lower() or None

    log.info("[API] /api/users récupéré, parsing…")

    users: Dict[str, Dict[str, Any]] = {}

    for u in root.findall("User"):
        pid = u.get("id")
        if not pid:
            continue

        # Champs de base
        username = u.get("username") or u.get("title") or f"user_{pid}"
        email = (u.get("email") or "").strip()
        avatar = u.get("thumb")

        # Flags
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

        # Subscription (nœud <subscription …/>)
        sub_node = u.find("subscription")
        subscription_active = None
        subscription_status = None
        subscription_plan = None
        if sub_node is not None:
            subscription_active = sub_node.get("active")
            subscription_status = sub_node.get("status")
            subscription_plan = sub_node.get("plan")

        # Rôle
        email_lower = email.lower() if email else ""

        if admin_email and email_lower == admin_email:
            plex_role = "owner"
        elif home_flag:
            plex_role = "home"
        else:
            plex_role = "friend"

        # Serveurs liés à ce user
        servers: List[Dict[str, Any]] = []
        for s in u.findall("Server"):
            servers.append(
                {
                    "machineIdentifier": s.get("machineIdentifier"),
                    "name": s.get("name"),
                    "home": 1 if s.get("home") == "1" else 0,
                    "owned": 1 if s.get("owned") == "1" else 0,
                    "allLibraries": 1 if s.get("allLibraries") == "1" else 0,
                    "numLibraries": int(s.get("numLibraries") or 0),
                    "lastSeenAt": s.get("lastSeenAt"),
                    "pending": 1 if s.get("pending") == "1" else 0,
                }
            )

        users[pid] = {
            "plex_id": pid,
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
            f"[API] User pid={pid} username={username!r} email={email!r} "
            f"role={plex_role}, servers={len(servers)}"
        )

    log.info(f"[API] /api/users → {len(users)} utilisateur(s) récupéré(s).")
    return users


# ---------------------------------------------------------------------------
# Sync USERS + user_servers (à partir de /api/users)
# ---------------------------------------------------------------------------

def sync_users_from_api(db: sqlite3.Connection) -> None:
    """
    - Récupère la durée d'abonnement par défaut (default_subscription_days)
    - Récupère un token Plex.tv dans servers
    - Appelle /api/users
    - Synchronise :
        * table users (infos de base + plex_role)
        * table user_servers (liens user ↔ serveur + options globales)
    - Marque les users disparus comme 'unfriended'
    - Nettoie les liens user_servers obsolètes (source='plex_api')
    """
    log.info("=== [SYNC USERS] Début synchronisation utilisateurs Plex (API Plex.tv) ===")

    # -------------------------------------------------------------------
    # 0) Paramètre : durée d'abonnement par défaut
    # -------------------------------------------------------------------
#    row = db.execute(
#        "SELECT default_subscription_days FROM settings LIMIT 1"
#    ).fetchone()
#
#    try:
#        default_days = int(row["default_subscription_days"]) if row and row["default_subscription_days"] is not None else 0
#    except Exception:
#        default_days = 0
#
#    log.info(f"[SYNC USERS] default_subscription_days = {default_days}")

    # -------------------------------------------------------------------
    # 1) Token Plex.tv
    # -------------------------------------------------------------------
    log.debug("[SYNC USERS] Récupération token Plex…")
    token = choose_account_token(db)
    if not token:
        log.error("[SYNC USERS] Aucun token Plex disponible → ABANDON.")
        return

    log.info("[SYNC USERS] Token trouvé (masqué dans les logs).")

    # -------------------------------------------------------------------
    # 2) Récupération USERS via Plex.tv
    # -------------------------------------------------------------------
    users_data = fetch_users_from_plex_api(token, db=db)
    if not users_data:
        log.warning("[SYNC USERS] Aucun utilisateur renvoyé par Plex.tv → rien à faire.")
        return

    # -------------------------------------------------------------------
    # 3) Mapping serveurs (machineIdentifier → id)
    # -------------------------------------------------------------------
    rows = db.execute(
        "SELECT id, server_identifier FROM servers WHERE type='plex'"
    ).fetchall()

    server_id_by_machine = {
        r["server_identifier"]: r["id"]
        for r in rows
        if r["server_identifier"]
    }

    log.info(
        f"[SYNC USERS] Serveurs Plex connus en base : "
        f"{len(server_id_by_machine)} (server_identifier non NULL)"
    )

    today = datetime.utcnow().date()
    seen_plex_ids: Set[str] = set()
    seen_user_servers: Set[Tuple[int, int]] = set()  # (user_id, server_id)

    # -------------------------------------------------------------------
    # 4) Upsert des USERS + liens user_servers
    # -------------------------------------------------------------------
    for plex_id, data in users_data.items():
        seen_plex_ids.add(plex_id)

        # -----------------------
        # Champs USER
        # -----------------------
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

        # --- USERS : SELECT ---
        row = db.execute(
            "SELECT * FROM users WHERE plex_id = ?",
            (plex_id,),
        ).fetchone()

        # -----------------------
        # UPDATE EXISTANT
        # -----------------------
        if row:
            db.execute(
                """
                UPDATE users
                SET username              = ?,
                    email                 = ?,
                    avatar                = ?,
                    plex_role             = ?,
                    home                  = ?,
                    protected             = ?,
                    restricted            = ?,
                    joined_at             = ?,
                    accepted_at           = ?,
                    subscription_active   = ?,
                    subscription_status   = ?,
                    subscription_plan     = ?
                WHERE id = ?
                """,
                (
                    username,
                    email,
                    avatar,
                    plex_role or row["plex_role"] or "unknown",
                    home_flag,
                    protected_flag,
                    restricted_flag,
                    joined_at,
                    accepted_at,
                    subscription_active,
                    subscription_status,
                    subscription_plan,
                    row["id"],
                ),
            )

            user_id = row["id"]
            log.debug(f"[SYNC USERS] MAJ user #{user_id} (plex_id={plex_id})")

        # -----------------------
        # INSERT NOUVEAU
        # -----------------------
        else:
            #expiration_date = None
            #if default_days > 0:
            #    expiration_date = (today + timedelta(days=default_days)).isoformat()

            db.execute(
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

            user_id = db.execute(
                "SELECT id FROM users WHERE plex_id = ?",
                (plex_id,),
            ).fetchone()["id"]

            log.info(f"[SYNC USERS] Nouvel utilisateur créé #{user_id} (plex_id={plex_id})")

        # -------------------------------------------------------------------
        # USER_SERVERS : mapping user ↔ serveurs
        # -------------------------------------------------------------------
        for srv in data.get("servers", []):
            machine_id = srv.get("machineIdentifier")
            if not machine_id:
                continue

            server_id = server_id_by_machine.get(machine_id)
            if not server_id:
                log.debug(
                    f"[SYNC USERS] Serveur machineIdentifier={machine_id} non trouvé en base "
                    f"→ ignoré pour plex_id={plex_id}"
                )
                continue

            seen_user_servers.add((user_id, server_id))

            # Champs serveur (API)
            owned = srv.get("owned", 0)
            all_lib = srv.get("allLibraries", 0)
            num_lib = srv.get("numLibraries", 0)
            pending = srv.get("pending", 0)
            last_seen = srv.get("lastSeenAt")

            # Champs permissions end-user
            allow_sync = data.get("allow_sync", 0)
            allow_cam = data.get("allow_camera_upload", 0)
            allow_channels = data.get("allow_channels", 0)
            allow_tuners = data.get("allow_tuners", 0)
            allow_subtitle_admin = data.get("allow_subtitle_admin", 0)

            # Champs filtres
            filter_all = data.get("filter_all")
            filter_movies = data.get("filter_movies")
            filter_music = data.get("filter_music")
            filter_photos = data.get("filter_photos")
            filter_tv = data.get("filter_television")
            reco_playlist_id = data.get("recommendations_playlist_id")

            # UPSERT
            db.execute(
                """
                INSERT INTO user_servers(
                    user_id, server_id,
                    owned, all_libraries, num_libraries, pending, last_seen_at,

                    allow_sync, allow_camera_upload, allow_channels,
                    allow_tuners, allow_subtitle_admin,

                    filter_all, filter_movies, filter_music, filter_photos, filter_television,
                    recommendations_playlist_id,

                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'plex_api')
                ON CONFLICT(user_id, server_id) DO UPDATE SET
                    owned                     = excluded.owned,
                    all_libraries             = excluded.all_libraries,
                    num_libraries             = excluded.num_libraries,
                    pending                   = excluded.pending,
                    last_seen_at              = excluded.last_seen_at,

                    allow_sync                = excluded.allow_sync,
                    allow_camera_upload       = excluded.allow_camera_upload,
                    allow_channels            = excluded.allow_channels,
                    allow_tuners              = excluded.allow_tuners,
                    allow_subtitle_admin      = excluded.allow_subtitle_admin,

                    filter_all                = excluded.filter_all,
                    filter_movies             = excluded.filter_movies,
                    filter_music              = excluded.filter_music,
                    filter_photos             = excluded.filter_photos,
                    filter_television         = excluded.filter_television,
                    recommendations_playlist_id = excluded.recommendations_playlist_id,

                    source = 'plex_api'
                """,
                (
                    user_id,
                    server_id,

                    owned,
                    all_lib,
                    num_lib,
                    pending,
                    last_seen,

                    allow_sync,
                    allow_cam,
                    allow_channels,
                    allow_tuners,
                    allow_subtitle_admin,

                    filter_all,
                    filter_movies,
                    filter_music,
                    filter_photos,
                    filter_tv,
                    reco_playlist_id,
                ),
            )

            log.debug(
                f"[SYNC USERS] user_servers upsert (user_id={user_id}, server_id={server_id}) "
                f"owned={owned}, allLib={all_lib}, allowSync={allow_sync}"
            )


    # -------------------------------------------------------------------
    # 5) Marquer les anciens users en UNFRIENDED (plus renvoyés par l'API)
    # -------------------------------------------------------------------
#    existing_users = db.execute("SELECT id, plex_id, plex_role FROM users").fetchall()
#    unfriended_count = 0
#
#    for row in existing_users:
#        pid = row["plex_id"]
#        if pid not in seen_plex_ids and row["plex_role"] != "unfriended":
#            db.execute(
#                """
#                UPDATE users
#                SET plex_role='unfriended', status='unfriended'
#                WHERE id = ?
#                """,
#                (row["id"],),
#            )
#            unfriended_count += 1
#            log.info(f"[SYNC USERS] User id={row['id']} plex_id={pid} marqué comme UNFRIENDED")

    # -------------------------------------------------------------------
    # 6) Nettoyage des liens user_servers obsolètes (source=plex_api)
    # -------------------------------------------------------------------
    rows = db.execute(
        """
        SELECT us.user_id, us.server_id
        FROM user_servers us
        JOIN servers s ON s.id = us.server_id
        WHERE us.source = 'plex_api'
          AND s.type    = 'plex'
        """
    ).fetchall()

    removed_links = 0
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
            removed_links += 1
            log.debug(
                f"[SYNC USERS] Lien user_servers supprimé (user_id={r['user_id']}, server_id={r['server_id']})"
            )

    db.commit()

    log.info(
        "=== [SYNC USERS] Fin synchronisation API Plex.tv === "
        f"users={len(seen_plex_ids)}, "
        f"liens user_servers={len(seen_user_servers)}, "
        f"liens supprimés={removed_links}, "
        #f"users_unfriended={unfriended_count}"
    )


# ---------------------------------------------------------------------------
# SYNC GLOBALE (pour compat avec l'ancien sync_all)
# ---------------------------------------------------------------------------

def sync_all(task_id=None, db: Optional[sqlite3.Connection] = None) -> None:
    """
    Nouvelle version simplifiée :
      - NE s'occupe plus des serveurs + bibliothèques (plus de plexapi ici)
      - Utilise UNIQUEMENT l'API Plex.tv /api/users
      - Synchronise :
          * users
          * user_servers
    """
    created_here = False
    if db is None:
        db = get_db()
        created_here = True

    log.info("=== [SYNC ALL] Début de la synchronisation Plex → DB (users only) ===")

    try:
        sync_users_from_api(db)

        # --- Sync libraries + access ---
        servers = db.execute("SELECT * FROM servers WHERE type='plex'").fetchall()


        for server in servers:
            # 1) Récupération des libraries via API locale
            libs = plex_get_libraries(server)
            sync_plex_libraries(db, server, libs)

            # 2) Charger PlexAPI pour récupérer les accès
            base_url = server["url"] or server["local_url"]
            token = server["token"]

            try:
                plex = PlexServer(base_url, token)
            except Exception as e:
                log.error(f"[SYNC ACCESS] Impossible de connecter PlexAPI au serveur {server['name']}: {e}")
                continue

            # 3) Synchronisation des accès user → libraries
            sync_plex_user_library_access(db, plex, server)

        log.info("=== [SYNC ALL] Synchronisation Plex terminée avec succès (users + libraries + access) ===")

    except Exception as e:
        error_msg = f"Erreur critique dans sync_all : {e}"
        log.error(error_msg, exc_info=True)
        raise
    finally:
        if created_here:
            try:
                db.close()
                log.debug("[SYNC ALL] Connexion DB interne fermée.")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# API POUR LE SCHEDULER (tasks_engine)
# ---------------------------------------------------------------------------

def run(task_id=None, db: Optional[sqlite3.Connection] = None):
    """
    Point d'entrée pour le scheduler VODUM.
    - Verbeux dans les logs TXT
    - Quelques logs en DB via task_logs pour l’UI
    - Laisse tasks_engine gérer status / last_run / next_run
    """
    log.info("=== [SYNC_PLEX] Tâche sync_plex démarrée ===")
    log.debug(f"[SYNC_PLEX] task_id={task_id}, db fourni={db is not None}")

    task_logs(task_id, "info", "Synchronisation Plex démarrée…")

    start = time.monotonic()

    try:
        sync_all(task_id, db=db)

        task_logs(task_id, "success", "Synchronisation Plex terminée avec succès.")
        duration = time.monotonic() - start
        log.info(f"=== [SYNC_PLEX] Terminé OK en {duration:.2f}s ===")
        return "OK"

    except Exception as e:
        log.error("[SYNC_PLEX] ERREUR pendant sync_plex", exc_info=True)
        task_logs(task_id, "error", f"Erreur pendant sync_plex : {e}")
        duration = time.monotonic() - start
        log.error(f"=== [SYNC_PLEX] ÉCHEC après {duration:.2f}s ===")
        raise


if __name__ == "__main__":
    sync_all()
