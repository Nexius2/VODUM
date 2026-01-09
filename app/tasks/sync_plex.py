
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Tuple, Optional

import requests
import xml.etree.ElementTree as ET
import json

from logging_utils import get_logger
from tasks_engine import task_logs
from plexapi.server import PlexServer  



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
        f"[SUBSCRIPTION] expiration_date initialisée pour vodum_user_id={vodum_user_id} → {expiration}"
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
        log.error(f"[ACCESS] media_user {media_user_id} introuvable")
        return []

    if media_user["type"] != "plex":
        log.error(f"[ACCESS] media_user {media_user_id} n'est pas un compte Plex")
        return []

    user_email = media_user["email"]

    if not user_email:
        log.error(f"[ACCESS] media_user {media_user_id} n'a pas d'email Plex")
        return []

    account = plex.myPlexAccount()

    try:
        user_acct = account.user(user_email)
    except Exception as e:
        log.error(f"[ACCESS] Impossible d'obtenir infos Plex pour {user_email}: {e}")
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
                f"[ACCESS] Erreur en parcourant sections user {user_email}: {e}"
            )

    return out



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
        log.warning(f"[SYNC ACCESS] Aucune library en base pour server={server_name} (id={server_id})")
        return

    # 2️⃣ Users liés à ce serveur
    users = db.query(
        """
        SELECT
            vu.email,
            mu.id AS media_user_id,
            mu.vodum_user_id AS vodum_user_id
        FROM media_users mu
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE mu.server_id = ?
          AND mu.type = 'plex'
        """,
        (server_id,),
    )

    if not users:
        log.info(f"[SYNC ACCESS] Aucun user lié à server={server_name} (id={server_id})")
        return

    processed_users = 0
    updated_users = 0
    skipped_no_email = 0

    # 3️⃣ Resync accès pour chaque user
    for u in users:
        email = u["email"]
        media_user_id = u["media_user_id"]
        vodum_user_id = u["vodum_user_id"]

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

        # Si pas d'email, on ne peut pas demander à Plex les accès (ta fonction plex_get_user_access est basée sur l'email)
        if not email:
            skipped_no_email += 1
            continue

        access = plex_get_user_access(db, plex, server_name, media_user_id)

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
        f"[SYNC ACCESS] Accès mis à jour pour serveur {server_name} "
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

    # suppression des libraries disparues
    for sid, lib_id in existing.items():
        if sid not in found:
            log.info(f"[SYNC LIBRARIES] Suppression library {lib_id} (section={sid})")

            # 🔥 ancien : shared_libraries → nouveau : media_user_libraries
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

    - Upsert table vodum_users (identité VODUM, via email)
    - Upsert table media_users (un compte Plex par serveur)
    - Nettoie les media_users Plex obsolètes
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
    # (external_user_id, server_id)
    seen_media_pairs: Set[Tuple[str, int]] = set()

    # ----------------------------------------------------
    # 4) Upsert vodum_users + media_users
    # ----------------------------------------------------
    for plex_id, data in users_data.items():
        seen_plex_ids.add(plex_id)

        username = data["username"]
        email = data["email"] or None
        avatar = data["avatar"]
        plex_role = data["plex_role"]

        home_flag = data.get("home", 0)
        protected_flag = data.get("protected", 0)
        restricted_flag = data.get("restricted", 0)

        joined_at = data.get("joined_at")
        accepted_at = data.get("accepted_at")

        # ------------------------------------------------
        # 4.1) VODUM_USERS : on cherche d'abord via user_identities (plex_id), sinon par email
        # ------------------------------------------------
        vodum_user_id = None

        # 4.1.1) Priorité: identité externe (même si email vide)
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

        # 4.1.2) Sinon: fallback par email
        if vodum_user_id is None and email:
            row = db.query_one(
                "SELECT id FROM vodum_users WHERE email = ?",
                (email,),
            )
            if row:
                vodum_user_id = row["id"]
                db.execute(
                    """
                    UPDATE vodum_users
                    SET username = COALESCE(username, ?)
                    WHERE id = ?
                    """,
                    (username, vodum_user_id),
                )

        # 4.1.3) Sinon: création
        if vodum_user_id is None:
            cur_v = db.execute(
                """
                INSERT INTO vodum_users(username, email, created_at, status)
                VALUES (?, ?, ?, 'active')
                """,
                (username, email, today.isoformat()),
            )
            vodum_user_id = cur_v.lastrowid
            log.info(f"[SYNC USERS] Nouvel vodum_user créé vodum_user_id={vodum_user_id} (plex_id={plex_id})")

        # 4.1.4) S'assure que l'identité plex est enregistrée (idempotent)
        db.execute(
            """
            INSERT OR IGNORE INTO user_identities(vodum_user_id, type, server_id, external_user_id)
            VALUES (?, 'plex', NULL, ?)
            """,
            (vodum_user_id, plex_id),
        )


        # ------------------------------------------------
        # 4.2) MEDIA_USERS : un compte Plex par serveur
        # ------------------------------------------------
        for srv in data.get("servers", []):
            machine_id = srv.get("machineIdentifier")
            if not machine_id:
                continue

            server_id = server_id_by_machine.get(machine_id)
            if not server_id:
                continue

            seen_media_pairs.add((plex_id, server_id))

            # ------------------------------------------------
            # DB v2: on stocke les options Plex (fidèles au serveur) dans media_users.details_json
            # -> overwrite à chaque sync (read-only UI pour l’instant)
            # ------------------------------------------------
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



            # existe déjà ?
            row_mu = db.query_one(
                """
                SELECT id
                FROM media_users
                WHERE server_id = ?
                  AND external_user_id = ?
                  AND type = 'plex'
                """,
                (server_id, plex_id),
            )

            if row_mu:
                media_user_id = row_mu["id"]

                db.execute(
                    """
                    UPDATE media_users
                    SET vodum_user_id = ?,
                        username       = ?,
                        email          = ?,
                        avatar         = ?,
                        type           = 'plex',
                        role           = ?,
                        joined_at      = ?,
                        accepted_at    = ?,
                        details_json   = ?
                    WHERE id = ?
                    """,
                    (
                        vodum_user_id,
                        username,
                        email,
                        avatar,
                        plex_role or "unknown",
                        joined_at,
                        accepted_at,
                        details_json,
                        media_user_id,
                    ),
                )

            else:
                cur_mu = db.execute(
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
                        joined_at,
                        accepted_at,
                        details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'plex', ?, ?, ?, ?)
                    """,
                    (
                        server_id,
                        vodum_user_id,
                        plex_id,
                        username,
                        email,
                        avatar,
                        plex_role or "unknown",
                        joined_at,
                        accepted_at,
                        details_json,
                    ),
                )
                media_user_id = cur_mu.lastrowid
                log.info(
                    f"[SYNC USERS] Nouveau media_user créé id={media_user_id} "
                    f"(server_id={server_id}, plex_id={plex_id})"
                )

    # ----------------------------------------------------
    # 5) Nettoyage media_users obsolètes (Plex)
    # ----------------------------------------------------
    rows = db.query(
        """
        SELECT mu.external_user_id, mu.server_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.type = 'plex'
          AND s.type  = 'plex'
        """
    )

    removed = 0
    for r in rows:
        key = (str(r["external_user_id"]), r["server_id"])
        if key not in seen_media_pairs:
            db.execute(
                """
                DELETE FROM media_users
                WHERE external_user_id = ?
                  AND server_id        = ?
                  AND type             = 'plex'
                """,
                (r["external_user_id"], r["server_id"]),
            )
            removed += 1

    log.info(
        f"=== [SYNC USERS] Fin sync Plex.tv : users={len(seen_plex_ids)}, "
        f"liens actifs={len(seen_media_pairs)}, media_users supprimés={removed} ==="
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

    log.info("=== [SYNC ALL] Début synchronisation Plex ===")

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
        raise RuntimeError("Aucun serveur Plex trouvé en base")

    any_success = False

    #
    # 3) Pour chaque serveur → sync libraries + accès users
    #
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

        # 🔥 nouvelle vérification
        if db.query_one("SELECT 1 FROM media_users LIMIT 1"):
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


