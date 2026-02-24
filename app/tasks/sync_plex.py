
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Tuple, Optional

import requests
import xml.etree.ElementTree as ET
import json

from logging_utils import get_logger
from tasks_engine import task_logs
from plexapi.server import PlexServer  

class TimeoutSession(requests.Session):
    """Session requests qui force un timeout par défaut."""
    def __init__(self, timeout=10, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)




# ---------------------------------------------------------------------------
# CONFIG & LOGGER
# ---------------------------------------------------------------------------


log = get_logger("sync_plex")

def ensure_expiration_date_on_first_access(db, vodum_user_id):
    """
    Initialise expiration_date UNIQUEMENT si :
      - expiration_date est NULL
      - default_subscription_days > 0
    """

    row = db.query_one(
        "SELECT expiration_date FROM vodum_users WHERE id = ?",
        (vodum_user_id,)
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
        "UPDATE vodum_users SET expiration_date = ? WHERE id = ?",
        (expiration, vodum_user_id)
    )

    log.info(
        f"[SUBSCRIPTION] expiration_date initialized for vodum_user_id={vodum_user_id} → {expiration}"
    )

    return True




# ---------------------------------------------------------------------------
# Token Plex.tv (pris dans la table servers)
# ---------------------------------------------------------------------------
def choose_account_token(db) -> Optional[str]:
    """
    Retourne un token Plex trouvé dans la table 'servers'.
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
        log.error("[SYNC USERS] No Plex token found in the table 'servers'.")
        return None

    token = row["token"]
    if not token:
        log.error("[SYNC USERS] Empty token in the table 'servers'.")
        return None

    return token

# ---------------------------------------------------------------------------
# Récupération Owner Plex
# ---------------------------------------------------------------------------
def sync_plex_owner_for_server(db, server):
    """
    Synchronise le OWNER du serveur Plex donné.
    - 1 serveur = 1 owner
    - ne touche PAS aux users
    """

    log.info(f"[OWNER] Sync owner for server {server['name']}")

    token = (server["token"] or "").strip()
    if not token:
        log.warning(f"[OWNER] {server['name']}: no token")
        return

    owner = fetch_admin_account_from_token(token)
    if not owner:
        log.error(f"[OWNER] {server['name']}: Unable to retrieve the owner")
        return

    plex_id = owner["plex_id"]
    username = owner.get("username") or f"user_{plex_id}"
    email = owner.get("email")
    avatar = owner.get("avatar")
    today = datetime.utcnow().date().isoformat()

    # -------------------------------------------------
    # 1) Résoudre / créer le vodum_user (GLOBAL)
    # -------------------------------------------------
    row = db.query_one(
        """
        SELECT vodum_user_id
        FROM user_identities
        WHERE type='plex'
          AND server_id IS NULL
          AND external_user_id = ?
        """,
        (plex_id,),
    )

    if row:
        vodum_user_id = row["vodum_user_id"]
    elif email:
        row = db.query_one(
            "SELECT id FROM vodum_users WHERE lower(email)=lower(?)",
            (email,),
        )
        if row:
            vodum_user_id = row["id"]
        else:
            vodum_user_id = db.execute(
                """
                INSERT INTO vodum_users(username, email, created_at, status)
                VALUES (?, ?, ?, 'active')
                """,
                (username, email, today),
            ).lastrowid
    else:
        vodum_user_id = db.execute(
            """
            INSERT INTO vodum_users(username, created_at, status)
            VALUES (?, ?, 'active')
            """,
            (username, today),
        ).lastrowid

    # identité plex globale
    db.execute(
        """
        INSERT OR IGNORE INTO user_identities(vodum_user_id, type, server_id, external_user_id)
        VALUES (?, 'plex', NULL, ?)
        """,
        (vodum_user_id, plex_id),
    )

    # -------------------------------------------------
    # 2) media_users POUR CE SERVEUR UNIQUEMENT
    # -------------------------------------------------
    row = db.query_one(
        """
        SELECT id, details_json
        FROM media_users
        WHERE server_id = ?
          AND type = 'plex'
          AND external_user_id = ?
        """,
        (server["id"], plex_id),
    )

    # ✅ Forcer options UI/logique pour l'owner
    # (cochées dans l'UI, filtres vides par défaut)
    owner_plex_share = {
        "allowSync": 1,
        "allowCameraUpload": 1,
        "allowChannels": 1,
        "filterMovies": "",
        "filterTelevision": "",
        "filterMusic": "",
    }

    if row:
        # Merge safe du JSON existant (ne pas casser d'autres clés)
        try:
            details = json.loads(row["details_json"] or "{}")
        except Exception:
            details = {}

        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share.update(owner_plex_share)
        details["plex_share"] = plex_share

        db.execute(
            """
            UPDATE media_users
            SET vodum_user_id = ?,
                username       = ?,
                email          = ?,
                avatar         = ?,
                role           = 'owner',
                details_json   = ?
            WHERE id = ?
            """,
            (vodum_user_id, username, email, avatar, json.dumps(details, ensure_ascii=False), row["id"]),
        )
    else:
        details = {"plex_share": owner_plex_share}

        db.execute(
            """
            INSERT INTO media_users(
                server_id,
                vodum_user_id,
                external_user_id,
                username,
                email,
                avatar,
                type,
                role,
                details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 'plex', 'owner', ?)
            """,
            (server["id"], vodum_user_id, plex_id, username, email, avatar, json.dumps(details, ensure_ascii=False)),
        )

    log.info(
        f"[OWNER] {server['name']}: owner OK "
        f"(plex_id={plex_id}, vodum_user_id={vodum_user_id})"
    )



# ---------------------------------------------------------------------------
# Récupération Libraries Plex (JSON local API)
# ---------------------------------------------------------------------------
def plex_get_user_access(db, plex, server_name, media_user_id: int):
    """
    Retourne les bibliothèques réellement partagées
    avec un utilisateur Plex (media_users).

    - nécessite media_users.type = 'plex'
    - utilise le champ media_users.email
    """

    media_user = db.query_one(
        """
        SELECT email, type
        FROM media_users
        WHERE id = ?
        """,
        (media_user_id,)
    )

    if not media_user:
        log.error(f"[ACCESS] media_user {media_user_id} Not found")
        return []

    if media_user["type"] != "plex":
        log.error(f"[ACCESS] media_user {media_user_id} Is not a Plex account")
        return []

    user_email = media_user["email"]

    if not user_email:
        log.error(f"[ACCESS] media_user {media_user_id} Does not have a Plex email")
        return []

    account = plex.myPlexAccount()

    try:
        user_acct = account.user(user_email)
    except Exception as e:
        log.error(f"[ACCESS] Unable to retrieve Plex information for {user_email}: {e}")
        return []

    out = []

    for srv in user_acct.servers:
        if srv.name != server_name:
            continue

        try:
            for section in srv.sections():
                if getattr(section, "shared", False):
                    out.append({
                        "title": section.title,
                        "key": str(section.key),
                    })
        except Exception as e:
            log.error(
                f"[ACCESS] Error while iterating over user sections {user_email}: {e}"
            )

    return out

def _plex_section_total_items(session, base_url: str, token: str, section_id: str, timeout: int = 10) -> int | None:
    # Astuce Plex: demander 0 item renvoie totalSize dans MediaContainer
    url = (
        f"{base_url.rstrip('/')}/library/sections/{section_id}/all"
        f"?X-Plex-Token={token}&X-Plex-Container-Start=0&X-Plex-Container-Size=0"
    )
    r = session.get(url, timeout=timeout)
    r.raise_for_status()

    root = ET.fromstring(r.text)

    # Plex renvoie généralement <MediaContainer ...> en racine
    mc = root if root.tag == "MediaContainer" else root.find("MediaContainer")
    if mc is None:
        return None

    total = mc.attrib.get("totalSize") or mc.attrib.get("size")
    try:
        return int(total)
    except Exception:
        return None



def sync_plex_user_library_access(db, plex, server):
    server_id = server["id"]
    server_name = server["name"]

    # 1️⃣ Mapping libraries du serveur
    libraries = db.query(
        """
        SELECT id, section_id
        FROM libraries
        WHERE server_id = ?
        """,
        (server_id,),
    )

    lib_map = {str(row["section_id"]): row["id"] for row in libraries}

    if not lib_map:
        log.warning(f"[SYNC ACCESS] No library found in the database for server={server_name} (id={server_id})")
        return

    # 2️⃣ Users liés à ce serveur
    users = db.query(
        """
        SELECT
            vu.email,
            mu.id AS media_user_id,
            mu.vodum_user_id AS vodum_user_id,
            mu.role AS role
        FROM media_users mu
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE mu.server_id = ?
          AND mu.type = 'plex'
        """,
        (server_id,),
    )


    if not users:
        log.info(f"[SYNC ACCESS] No user linked to server={server_name} (id={server_id})")
        return

    processed_users = 0
    updated_users = 0
    skipped_no_email = 0

    # 3️⃣ Resync accès pour chaque user
    for u in users:
        email = u["email"]
        media_user_id = u["media_user_id"]
        vodum_user_id = u["vodum_user_id"]
        role = (u["role"] or "").strip().lower()

        processed_users += 1

        # Nettoyer les anciens accès pour CE serveur (toujours)
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


        has_access = False

        # ✅ Cas spécial OWNER : on force toutes les libraries du serveur en ON
        if role == "owner":
            for lib_id in lib_map.values():
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (media_user_id, lib_id),
                )
            has_access = True

        else:
            # Sinon, logique normale basée sur l'API Plex (nécessite un email)
            if not email:
                skipped_no_email += 1
                continue

            access = plex_get_user_access(db, plex, server_name, media_user_id)

            for lib in access:
                sec_id = str(lib.get("key") or "")
                lib_id = lib_map.get(sec_id)
                if not lib_id:
                    continue

                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (media_user_id, lib_id),
                )

                has_access = True

        # ✅ ici on passe bien vodum_user_id (pas media_user_id)
        if has_access:
            ensure_expiration_date_on_first_access(db, vodum_user_id)

        updated_users += 1

    log.info(
        f"[SYNC ACCESS] Access updated for server {server_name} "
        f"(users en base={len(users)}, traités={processed_users}, maj={updated_users}, sans_email={skipped_no_email})"
    )






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
        log.error(f"[SYNC LIBRARIES] Server {server['name']} without URL or token.")
        return []

    url = f"{base_url}/library/sections"
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"[SYNC LIBRARIES] Error API {url}: {e}")
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

    log.info(f"[SYNC LIBRARIES] {len(out)} Libraries detected on {server['name']}")
    return out

def sync_plex_libraries(db, server, libraries):
    """
    Synchronise les libraries Plex pour un serveur donné.
    + met à jour item_count.
    """
    server_id = server["id"]

    base_url = (server.get("url") or server.get("local_url") or server.get("public_url") or "").rstrip("/")
    token = (server.get("token") or "").strip()

    rows = db.query(
        "SELECT id, section_id FROM libraries WHERE server_id = ?",
        (server_id,),
    )

    existing = {row["section_id"]: row["id"] for row in rows}
    found = set()

    # Session requests avec timeout par défaut
    session = requests.Session()

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

        # ✅ item_count (best effort)
        if base_url and token:
            try:
                count = _plex_section_total_items(session, base_url, token, str(sid), timeout=10)
            except Exception:
                count = None

            if count is not None:
                db.execute(
                    "UPDATE libraries SET item_count = ? WHERE server_id = ? AND section_id = ?",
                    (int(count), server_id, str(sid)),
                )

    # suppression des libraries disparues
    for sid, lib_id in existing.items():
        if sid not in found:
            log.info(f"[SYNC LIBRARIES] Library removal {lib_id} (section={sid})")

            db.execute(
                "DELETE FROM media_user_libraries WHERE library_id = ?",
                (lib_id,),
            )

            db.execute(
                "DELETE FROM libraries WHERE id = ?",
                (lib_id,),
            )



  






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
        resp = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        log.error(f"[API] Network error on {url}: {e}")
        return None

    if resp.status_code != 200:
        log.error(f"[API] {url} → HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        root = ET.fromstring(resp.content)
        return root
    except Exception as e:
        log.error(f"[API] Invalid XML for {url}: {e}")
        return None

def fetch_admin_account_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Récupère le compte Plex lié au token (owner/admin) via Plex.tv /users/account.
    Renvoie un dict au même format que fetch_users_from_plex_api() (sans servers).
    """
    url = "https://plex.tv/users/account"
    root = fetch_xml(url, token)
    if root is None:
        log.error("[API] Unable to retrieve /users/account")
        return None

    # Selon les réponses Plex, ça peut être <user ...> ou autre, on prend les attribs
    plex_id = root.get("id")
    if not plex_id:
        log.error("[API] /users/account does not contain an ID")
        return None

    username = root.get("username") or root.get("title") or f"user_{plex_id}"
    email = (root.get("email") or "").strip() or None

    # L’attribut le plus courant est "thumb"
    avatar = root.get("thumb") or root.get("avatar")

    return {
        "plex_id": str(plex_id),
        "username": username,
        "email": email,
        "avatar": avatar,

        # On marque distinctement, tu trieras après
        "plex_role": "owner",

        # Flags inconnus ici, on met 0 par défaut
        "home": 0,
        "protected": 0,
        "restricted": 0,

        # Options Plex inconnues sur /users/account
        "allow_sync": 1,
        "allow_camera_upload": 1,
        "allow_channels": 1,

        "filter_all": None,
        "filter_movies": None,
        "filter_television": None,
        "filter_music": None,
        "filter_photos": None,
        "recommendations_playlist_id": None,

        "joined_at": None,
        "accepted_at": None,

        "subscription_active": None,
        "subscription_status": None,
        "subscription_plan": None,

        # IMPORTANT: sera rempli plus bas avec tous les serveurs
        "servers": [],
    }


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
        log.error("[API] Unable to retrieve /api/users → Aborted.")
        return {}

    # ----------------------------------------------------
    # Email admin (pour déterminer le rôle owner)
    # ----------------------------------------------------
    admin_email = None
    if db is not None:
        row = db.query_one("SELECT admin_email FROM settings LIMIT 1")
        if row:
            admin_email = (row["admin_email"] or "").strip().lower() or None

    log.info("[API] /api/users Retrieved, parsing…")

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

    log.info(f"[API] /api/users → {len(users)} User(s) retrieved.")
    return users



# ---------------------------------------------------------------------------
# Sync USERS + user_servers (à partir de /api/users)
# ---------------------------------------------------------------------------
def sync_users_from_api(db) -> None:
    log.info("=== [SYNC USERS] Starting Plex user synchronization (API Plex.tv) ===")

    # ----------------------------------------------------
    # 1) Récupérer TOUS les serveurs Plex avec token
    #    (PAS de dédupe par token : on exécute /api/users par serveur)
    # ----------------------------------------------------
    server_rows = db.query(
        """
        SELECT id, name, token
        FROM servers
        WHERE type='plex'
          AND token IS NOT NULL
          AND token != ''
        ORDER BY id
        """
    )
    if not server_rows:
        raise RuntimeError("[SYNC USERS] Aucun serveur Plex avec token en base.")

    # ----------------------------------------------------
    # 2) Mapping serveurs Plex (machineIdentifier → id)
    # ----------------------------------------------------
    rows = db.query("SELECT id, server_identifier, name FROM servers WHERE type='plex'")

    server_id_by_machine = {
        (r["server_identifier"] or "").strip(): r["id"]
        for r in rows
        if (r["server_identifier"] or "").strip()
    }

    log.info(f"[SYNC USERS] Known Plex servers (server_identifier non vide) : {len(server_id_by_machine)}")

    # ----------------------------------------------------
    # 3) Appeler /api/users pour CHAQUE serveur, puis MERGER
    # ----------------------------------------------------
    users_data: Dict[str, Dict[str, Any]] = {}
    servers_ok = 0

    def merge_user(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
        # Identité : garder le plus complet
        for k in ("username", "email", "avatar"):
            if not (dst.get(k) or "").strip():
                dst[k] = src.get(k)

        # Flags : garder le plus "vrai"
        for k in ("home", "protected", "restricted",
                  "allow_sync", "allow_camera_upload", "allow_channels"):
            if src.get(k) and not dst.get(k):
                dst[k] = src.get(k)

        # Rôle : home > friend > unknown (on ne force PAS owner ici)
        def rank(role: str) -> int:
            role = (role or "").lower()
            if role == "home":
                return 2
            if role == "friend":
                return 1
            return 0

        if rank(src.get("plex_role")) > rank(dst.get("plex_role")):
            dst["plex_role"] = src.get("plex_role")

        # Serveurs : union par machineIdentifier
        dst_servers = dst.get("servers") or []
        src_servers = src.get("servers") or []

        dst_mids = {s.get("machineIdentifier") for s in dst_servers if s.get("machineIdentifier")}
        for s in src_servers:
            mid = s.get("machineIdentifier")
            if mid and mid not in dst_mids:
                dst_servers.append(s)
                dst_mids.add(mid)

        dst["servers"] = dst_servers
        return dst

    for idx, srv in enumerate(server_rows, start=1):
        token = (srv["token"] or "").strip()
        if not token:
            continue

        log.info(f"[SYNC USERS] server #{idx}/{len(server_rows)}: {srv['name']} (server_id={srv['id']}) -> /api/users")

        data = fetch_users_from_plex_api(token, db=db)
        if not data:
            log.warning(f"[SYNC USERS] {srv['name']}: /api/users blank or error")
            continue

        servers_ok += 1
        log.info(f"[SYNC USERS] {srv['name']}: {len(data)} retrieved user(s)")

        for plex_id, u in data.items():
            if plex_id in users_data:
                users_data[plex_id] = merge_user(users_data[plex_id], u)
            else:
                users_data[plex_id] = u

    if not users_data:
        raise RuntimeError("[SYNC USERS] No users returned by Plex.tv (all servers).")

    log.info(
        f"[SYNC USERS] /api/users global MERGE: {len(users_data)} uniques user(s) "
        f"(serveurs_ok={servers_ok}/{len(server_rows)})"
    )

    # ----------------------------------------------------
    # 3.b) Owner par serveur (server_id -> owner_plex_id)
    # ----------------------------------------------------
    owner_plex_id_by_server_id: Dict[int, str] = {}

    for srv in server_rows:
        sid = int(srv["id"])
        token = (srv["token"] or "").strip()
        if not token:
            continue

        owner = fetch_admin_account_from_token(token)
        if not owner or not owner.get("plex_id"):
            log.warning(f"[SYNC USERS] {srv['name']}: Unable to determine owner via /users/account")
            continue

        owner_plex_id_by_server_id[sid] = str(owner["plex_id"])
        log.info(f"[SYNC USERS] {srv['name']}: owner plex_id={owner_plex_id_by_server_id[sid]}")


    # ----------------------------------------------------
    # 4) Upsert vodum_users + media_users (IDENTIQUE à ton code)
    #     + logs si machineIdentifier non mappable
    # ----------------------------------------------------
    today = datetime.utcnow().date()
    seen_plex_ids: Set[str] = set()
    seen_media_pairs: Set[Tuple[str, int]] = set()

    for plex_id, data in users_data.items():
        seen_plex_ids.add(plex_id)

        username = data["username"]
        email = data["email"] or None
        avatar = data["avatar"]
        plex_role = data["plex_role"]

        joined_at = data.get("joined_at")
        accepted_at = data.get("accepted_at")

        # 4.1) VODUM_USERS (identique)
        vodum_user_id = None

        row = db.query_one(
            """
            SELECT vodum_user_id
            FROM user_identities
            WHERE type = 'plex'
              AND server_id IS NULL
              AND external_user_id = ?
            """,
            (plex_id,),
        )
        if row:
            vodum_user_id = row["vodum_user_id"]

        if vodum_user_id is None and email:
            row = db.query_one("SELECT id, username FROM vodum_users WHERE email = ?", (email,))
            if row:
                vodum_user_id = row["id"]

                # Si le user a été créé via VODUM, on a souvent username=email.split('@')[0].
                # Dans ce cas, on le remplace par le vrai username Plex quand on le découvre,
                # pour éviter des usernames différents entre instances.
                current_username = (row.get("username") or "").strip()
                email_local = (email.split("@", 1)[0] if email else "").strip()

                if (not current_username) or (current_username.lower() == email_local.lower()):
                    db.execute(
                        "UPDATE vodum_users SET username = ? WHERE id = ?",
                        (username, vodum_user_id),
                    )

        if vodum_user_id is None:
            cur_v = db.execute(
                """
                INSERT INTO vodum_users(username, email, created_at, status)
                VALUES (?, ?, ?, 'active')
                """,
                (username, email, today.isoformat()),
            )
            vodum_user_id = cur_v.lastrowid
            log.info(f"[SYNC USERS] New vodum_user created vodum_user_id={vodum_user_id} (plex_id={plex_id})")

        db.execute(
            """
            INSERT OR IGNORE INTO user_identities(vodum_user_id, type, server_id, external_user_id)
            VALUES (?, 'plex', NULL, ?)
            """,
            (vodum_user_id, plex_id),
        )

        # 4.2) MEDIA_USERS (identique + log mismatch)
        for srv in data.get("servers", []):
            machine_id = (srv.get("machineIdentifier") or "").strip()
            if not machine_id:
                continue

            server_id = server_id_by_machine.get(machine_id)
            if not server_id:
                # 🔥 log crucial : tu verras immédiatement quel machineIdentifier ne matche pas ta DB
                log.warning(
                    f"[SYNC USERS] machineIdentifier not mapped in the database: {machine_id} "
                    f"(user plex_id={plex_id}, username={username!r})"
                )
                continue

            seen_media_pairs.add((plex_id, server_id))

            # Rôle PAR SERVEUR (source de vérité)
            # - owner : uniquement si plex_id == owner du serveur (via /users/account du token serveur)
            # - home  : si user est home (ou srv.home)
            # - friend: sinon
            srv_home = 1 if str(srv.get("home") or "0") == "1" else 0

            server_owner_plex_id = owner_plex_id_by_server_id.get(int(server_id))
            if server_owner_plex_id and str(plex_id) == str(server_owner_plex_id):
                role_for_server = "owner"
            elif (data.get("home") or 0) == 1 or srv_home == 1 or (data.get("plex_role") or "").lower() == "home":
                role_for_server = "home"
            else:
                role_for_server = "friend"




            details_json = json.dumps(
                {
                    "plex_share": {
                        "allowSync": 1 if data.get("allow_sync") else 0,
                        "allowCameraUpload": 1 if data.get("allow_camera_upload") else 0,
                        "allowChannels": 1 if data.get("allow_channels") else 0,
                        "filterMovies": data.get("filter_movies") or "",
                        "filterTelevision": data.get("filter_television") or "",
                        "filterMusic": data.get("filter_music") or "",
                    }
                },
                ensure_ascii=False
            )

            # IMPORTANT : si le user a été créé via VODUM avant que Plex ne renvoie un plex_id,
            # on peut avoir un "placeholder" media_users avec external_user_id NULL.
            # Ici, on tente d'abord de matcher sur plex_id, puis on "récupère" le placeholder
            # (server_id + vodum_user_id + external_user_id IS NULL) pour éviter les doublons.
            row_mu = db.query_one(
                """
                SELECT id
                FROM media_users
                WHERE server_id = ?
                  AND type = 'plex'
                  AND (external_user_id = ? OR (external_user_id IS NULL AND vodum_user_id = ?))
                ORDER BY id DESC
                LIMIT 1
                """,
                (server_id, plex_id, vodum_user_id),
            )

            if row_mu:
                db.execute(
                    """
                    UPDATE media_users
                    SET vodum_user_id     = ?,
                        external_user_id = ?,
                        username         = ?,
                        email            = ?,
                        avatar           = ?,
                        type             = 'plex',
                        role             = ?,
                        joined_at        = ?,
                        accepted_at      = ?,
                        details_json     = ?
                    WHERE id = ?
                    """,
                    (vodum_user_id, plex_id, username, email, avatar, role_for_server,
                     joined_at, accepted_at, details_json, row_mu["id"]),
                )

                # Nettoyage : supprime d'éventuels placeholders restants (external_user_id NULL)
                db.execute(
                    """
                    DELETE FROM media_users
                    WHERE server_id = ?
                      AND type = 'plex'
                      AND vodum_user_id = ?
                      AND external_user_id IS NULL
                    """,
                    (server_id, vodum_user_id),
                )
            else:
                cur_mu = db.execute(
                    """
                    INSERT INTO media_users(
                        server_id, vodum_user_id, external_user_id,
                        username, email, avatar,
                        type, role, joined_at, accepted_at, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'plex', ?, ?, ?, ?)
                    """,
                    (server_id, vodum_user_id, plex_id,
                     username, email, avatar,
                     role_for_server, joined_at, accepted_at, details_json),
                )
                log.info(
                    f"[SYNC USERS] New media_user created id={cur_mu.lastrowid} "
                    f"(server_id={server_id}, plex_id={plex_id})"
                )

    log.info(
        f"=== [SYNC USERS] Finished : users_uniques={len(seen_plex_ids)}, liens_media_users={len(seen_media_pairs)} ==="
    )






# ---------------------------------------------------------------------------
# SYNC GLOBALE (pour compat avec l'ancien sync_all)
# ---------------------------------------------------------------------------

def sync_all(task_id=None, db=None) -> None:
    """
    Synchronisation complète Plex :

      - Synchronise les utilisateurs Plex (création/MAJ media_users)
      - Synchronise les libraries Plex
      - Synchronise les accès users → libraries

    IMPORTANT :
      - DBManager uniquement
      - aucun commit / rollback
      - aucune ouverture / fermeture DB
    """

    if db is None:
        raise RuntimeError("sync_all() doit recevoir un DBManager")

    log.info("=== [SYNC ALL] Starting Plex synchronization ===")

    #
    # 1) Sync utilisateurs depuis Plex.tv (/api/users)
    #
    sync_users_from_api(db)

    #
    # 2) Récupération des serveurs Plex
    #
    servers = db.query(
        "SELECT * FROM servers WHERE type='plex'"
    )

    if not servers:
        raise RuntimeError("No Plex server found in the database")

    any_success = False

    #
    # 3) Pour chaque serveur → sync libraries + accès users
    #
    for server in servers:
        # IMPORTANT: sqlite3.Row -> dict, pour supporter .get() et éviter les crash
        server = dict(server)

        server_name = server.get("name") or f"server_{server.get('id')}"

        log.info(f"[SYNC ALL] Plex server: {server_name}")

        # --- Libraries ---
        try:
            libs = plex_get_libraries(server)
            sync_plex_libraries(db, server, libs)
            sync_plex_owner_for_server(db, server)

        except Exception as e:
            log.error(
                f"[SYNC LIBS] Library synchronization error for {server_name}: {e}",
                exc_info=True
            )
            continue

        # --- Accès utilisateurs ---
        base_url = server["url"] or server["local_url"]
        token = server["token"]

        if not base_url or not token:
            log.warning(
                f"[SYNC ACCESS] Server {server_name} No URL/token → access ignored"
            )
            continue

        try:
            # 🔎 logs ciblage + garde-fou réseau
            log.info(f"[SYNC ACCESS] Attempting PlexAPI connection → {server_name} base_url={base_url}")

            # ⏱️ timeout forcé pour plexapi
            session = TimeoutSession(timeout=20)

            # petit ping très parlant (et timeout)
            try:
                r = session.get(f"{base_url}/identity")
                log.info(f"[SYNC ACCESS] /identity OK ({server_name}) HTTP={r.status_code}")
            except Exception as e:
                log.error(f"[SYNC ACCESS] /identity KO ({server_name}) : {e}")
                raise

            plex = PlexServer(base_url, token, session=session)

            log.info(f"[SYNC ACCESS] PlexAPI connected ({server_name}) → Starting user access synchronization")
            sync_plex_user_library_access(db, plex, server)
            log.info(f"[SYNC ACCESS] User access synchronization completed ({server_name})")

            any_success = True

        except Exception as e:
            log.error(
                f"[SYNC ACCESS] Connection or synchronization failed for {server_name}: {e}",
                exc_info=True
            )
            continue


    if not any_success:
        raise RuntimeError("No Plex server could be synchronized")

    log.info("=== [SYNC ALL] Plex synchronization completed ===")




# ---------------------------------------------------------------------------
# API POUR LE SCHEDULER (tasks_engine)
# ---------------------------------------------------------------------------
def run(task_id: int, db):
    """
    Point d'entrée pour le scheduler VODUM.
    """

    log.info("=== [SYNC_PLEX] sync_plex task started ===")
    log.debug(f"[SYNC_PLEX] task_id={task_id}")

    task_logs(task_id, "info", "Plex synchronization started…")

    start = time.monotonic()

    try:
        sync_all(task_id, db=db)

        duration = time.monotonic() - start
        log.info(f"=== [SYNC_PLEX] Completed successfully in {duration:.2f}s ===")

        # 🔥 nouvelle vérification
        if db.query_one("SELECT 1 FROM media_users LIMIT 1"):
            task_logs(task_id, "success", "Plex synchronization completed successfully.")
        else:
            task_logs(task_id, "info", "Plex synchronization completed — no users found.")

    except Exception as e:
        duration = time.monotonic() - start
        log.error(
            f"=== [SYNC_PLEX] FAILED after {duration:.2f}s ===",
            exc_info=True,
        )
        task_logs(task_id, "error", f"Error during sync_plex : {e}")
        raise


