
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Tuple, Optional

import xml.etree.ElementTree as ET
import json

from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import task_logs
from plexapi.server import PlexServer  
from core.plex_rate_limit import wait_for_plex_slot
from core.plex_connection import plex_candidate_base_urls, find_working_plex_base_url
from core.server_cooldown import should_skip_unreachable_server, mark_server_unreachable, clear_server_cooldown
from core.http_security import plex_server_http_session
from core.providers.plex_invitation_state import (
    merge_accepted_plex_media_user,
    plex_invite_state_payload,
)
from core.plex_access_identity import (
    is_pending_invite_media_user as _is_pending_plex_invite_media_user,
    row_get as _row_value,
)
from core.plex_sync_config import get_plex_user_import_mode
from core.plex_sync_api import (
    fetch_admin_account_from_token,
    fetch_shared_server_users,
    fetch_users_from_plex_api,
)
from core.plex_sync_orchestrator import sync_all_servers
from core.plex_library_access import (
    apply_media_user_library_diff_for_server as _apply_media_user_library_diff_for_server,
)
from core.plex_owner_sync import sync_plex_owner_for_server
from core.plex_library_sync import plex_get_libraries, sync_plex_libraries

# ---------------------------------------------------------------------------
# CONFIG & LOGGER
# ---------------------------------------------------------------------------


log = get_logger("sync_plex")


def ensure_expiration_date_on_first_access(db, vodum_user_id):
    """
    Conserve le contrat historique de synchronisation.

    Cette fonction n'est pas appelée lors d'un simple partage de bibliothèque :
    l'activation effective reste déclenchée au premier playback.
    """
    row = db.query_one(
        "SELECT expiration_date FROM vodum_users WHERE id = ?",
        (vodum_user_id,),
    )
    if not row or row["expiration_date"] is not None:
        return False

    row = db.query_one(
        "SELECT default_subscription_days FROM settings LIMIT 1"
    )
    try:
        days = int(row["default_subscription_days"]) if row else 0
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return False

    expiration = (datetime.utcnow().date() + timedelta(days=days)).isoformat()
    db.execute(
        "UPDATE vodum_users SET expiration_date = ? WHERE id = ?",
        (expiration, vodum_user_id),
    )
    log.info(
        "[SUBSCRIPTION] expiration_date initialized for "
        f"vodum_user_id={vodum_user_id} → {expiration}"
    )
    return True


def _plex_base_urls(server) -> list[str]:
	return plex_candidate_base_urls(server)


def _pick_plex_base_url(server) -> str:
	urls = _plex_base_urls(server)
	return urls[0] if urls else ""


def _find_working_plex_base_url(server, endpoint="/identity", accept="application/xml") -> str:
	return find_working_plex_base_url(
		server,
		endpoint=endpoint,
		accept=accept,
	)


def _ensure_plex_server_identity(db, server) -> None:
    """
    Force la récupération du vrai machineIdentifier Plex avant sync_users_from_api().
    Sans ça, un serveur fraîchement ajouté garde l'UUID temporaire VODUM,
    et les users Plex récupérés via /api/users ne peuvent pas être reliés au bon serveur.
    """
    server_id = int(server["id"])
    base_url = _find_working_plex_base_url(server, endpoint="/identity", accept="application/xml")
    token = (server.get("token") or "").strip()

    if not base_url or not token:
        return

    try:
        wait_for_plex_slot(base_url)
        resp = plex_server_http_session(server).get(
            f"{base_url}/identity",
            headers={
                "X-Plex-Token": token,
                "Accept": "application/xml",
            },
            timeout=20,
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        machine_id = (
            root.attrib.get("machineIdentifier")
            or root.attrib.get("machineIdentifier".lower())
            or ""
        ).strip()

        server_name = (
            root.attrib.get("friendlyName")
            or root.attrib.get("name")
            or server.get("name")
            or ""
        ).strip()

        if machine_id:
            db.execute(
                """
                UPDATE servers
                SET server_identifier = ?,
                    name = CASE
                        WHEN ? != '' THEN ?
                        ELSE name
                    END
                WHERE id = ?
                """,
                (machine_id, server_name, server_name, server_id),
            )

            log.info(
                f"[SYNC IDENTITY] server_id={server_id} machineIdentifier={machine_id} name={server_name!r}"
            )

    except Exception as e:
        log.warning(
            f"[SYNC IDENTITY] Unable to refresh Plex identity for server_id={server_id}: {e}"
        )

# ---------------------------------------------------------------------------
# Récupération Owner Plex
# ---------------------------------------------------------------------------
def plex_get_user_access(db, plex, server_name, media_user_id: int):
    """
    Retourne les bibliothèques réellement partagées
    avec un utilisateur Plex (media_users).

    Retour :
    - list[dict] => accès récupéré correctement
    - []         => accès récupéré correctement mais aucune bibliothèque
    - None       => erreur Plex/API, donc on ne doit rien supprimer en base
    """

    media_user = db.query_one(
        """
        SELECT email, username, type
        FROM media_users
        WHERE id = ?
        """,
        (media_user_id,)
    )

    if not media_user:
        log.error(f"[ACCESS] media_user {media_user_id} Not found")
        return None

    if media_user["type"] != "plex":
        log.error(f"[ACCESS] media_user {media_user_id} Is not a Plex account")
        return None

    user_email = media_user["email"]

    if not user_email:
        log.error(f"[ACCESS] media_user {media_user_id} Does not have a Plex email")
        return None

    try:
        account = plex.myPlexAccount()

        user_acct = None

        masked_email = "unknown"

        if user_email and "@" in user_email:
            name, domain = user_email.split("@", 1)

            if len(name) > 2:
                masked_email = f"{name[0]}*****@{domain}"
            else:
                masked_email = f"*****@{domain}"

        # Retry via email
        for attempt in range(3):
            try:
                user_acct = account.user(user_email)

                if user_acct:
                    break

            except Exception as retry_error:
                log.warning(
                    f"[ACCESS] Plex lookup retry "
                    f"{attempt + 1}/3 failed for {masked_email}: "
                    f"{retry_error}"
                )

                time.sleep(2)

        # Fallback username
        if not user_acct:
            username = (media_user.get("username") or "").strip()

            if username:
                try:
                    log.info(
                        f"[ACCESS] Trying Plex lookup via username "
                        f"for {masked_email} -> {username}"
                    )

                    user_acct = account.user(username)

                    if user_acct:
                        log.info(
                            f"[ACCESS] Plex lookup recovered "
                            f"via username for {masked_email}"
                        )

                except Exception as username_error:
                    log.warning(
                        f"[ACCESS] Username lookup failed "
                        f"for {masked_email} ({username}): "
                        f"{username_error}"
                    )

        if not user_acct:
            log.warning(
                f"[ACCESS] Plex user not found "
                f"for {masked_email}"
            )
            return None

    except Exception as e:
        log.error(
            f"[ACCESS] Unable to retrieve Plex information "
            f"for {masked_email}: {e}"
        )
        return None

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
            return None

    return out

def sync_plex_user_library_access(db, plex, server):
    server_id = server["id"]
    server_name = server["name"]

    # 1ï¸âƒ£ Mapping libraries du serveur
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
            mu.role AS role,
            mu.username AS username,
            mu.external_user_id AS external_user_id,
            mu.accepted_at AS accepted_at,
            mu.details_json AS details_json
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
    preserved_pending = 0
    skipped_pending_jobs = 0

    # 3️⃣ Resync accès pour chaque user
    for u in users:
        email = u["email"]
        media_user_id = u["media_user_id"]
        vodum_user_id = u["vodum_user_id"]
        role = (u["role"] or "").strip().lower()
        username = _row_value(u, "username", "")

        processed_users += 1

        # ✅ Ignore users that should no longer exist on Plex
        vodum_user = db.query_one(
            """
            SELECT status
            FROM vodum_users
            WHERE id = ?
            """,
            (vodum_user_id,),
        )

        user_status = (
            str(vodum_user["status"]).strip().lower()
            if vodum_user and vodum_user["status"]
            else ""
        )

        if user_status in ("expired", "disabled", "removed"):
            log.info(
                f"[SYNC SKIPPED] ignored user status={user_status} "
                f"(vodum_user_id={vodum_user_id}, "
                f"media_user_id={media_user_id}, "
                f"server_id={server_id})"
            )
            continue

        # ✅ Cas spécial : invitation Plex pas encore acceptée
        # On NE TOUCHE PAS aux media_user_libraries déjà prévues en DB.
        if role != "owner" and _is_pending_plex_invite_media_user(u):
            preserved_pending += 1
            log.info(
                f"[SYNC ACCESS] Pending Plex invite preserved for user={username!r} "
                f"(media_user_id={media_user_id}, server={server_name})"
            )
            continue

        # ✅ Cas spécial : job Plex encore en attente / en cours
        # On SKIP complètement cet utilisateur pour éviter qu'un DELETE brutal
        # efface un état qui doit encore être appliqué par apply_plex_access_updates.
        pending_job = db.query_one(
            """
            SELECT 1
            FROM media_jobs
            WHERE vodum_user_id = ?
              AND server_id = ?
              AND provider = 'plex'
              AND status IN ('queued', 'running')
              AND action IN ('grant', 'revoke', 'sync')
            LIMIT 1
            """,
            (vodum_user_id, server_id),
        )

        if pending_job:
            skipped_pending_jobs += 1
            log.info(
                f"[SYNC SKIPPED] pending media job detected "
                f"(vodum_user_id={vodum_user_id}, media_user_id={media_user_id}, server_id={server_id})"
            )
            continue

        desired_library_ids = set()
        has_access = False

        # ✅ OWNER : toutes les libraries du serveur
        if role == "owner":
            desired_library_ids = {int(lib_id) for lib_id in lib_map.values()}
            has_access = bool(desired_library_ids)

        else:
            # logique normale basée sur l'API Plex
            if not email:
                skipped_no_email += 1
                continue

            access = plex_get_user_access(db, plex, server_name, media_user_id)

            # ⚠️ Si Plex répond mal / erreur API, on ne supprime rien
            if access is None:
                log.warning(
                    f"[SYNC SKIPPED] access fetch failed for "
                    f"vodum_user_id={vodum_user_id} media_user_id={media_user_id} server_id={server_id}"
                )
                continue

            for lib in access:
                sec_id = str(lib.get("key") or "")
                lib_id = lib_map.get(sec_id)
                if not lib_id:
                    continue
                desired_library_ids.add(int(lib_id))

            has_access = bool(desired_library_ids)

        before_ids, added_ids, removed_ids = _apply_media_user_library_diff_for_server(
            db,
            media_user_id=media_user_id,
            server_id=server_id,
            desired_library_ids=desired_library_ids,
        )

        if added_ids or removed_ids:
            log.info(
                f"[SYNC OVERWRITE] vodum_user_id={vodum_user_id} media_user_id={media_user_id} "
                f"server_id={server_id} before={sorted(before_ids)} "
                f"after={sorted(desired_library_ids)} "
                f"added={added_ids} removed={removed_ids}"
            )

        # ✅ uniquement si accès réel trouvé
        updated_users += 1

    log.info(
        f"[SYNC ACCESS] Access updated for server {server_name} "
        f"(users en base={len(users)}, traités={processed_users}, maj={updated_users}, "
        f"sans_email={skipped_no_email}, pending_preserved={preserved_pending}, "
        f"sync_skipped_pending_jobs={skipped_pending_jobs})"
    )






def sync_users_from_api(db) -> None:
    log.info("=== [SYNC USERS] Starting Plex user synchronization (API Plex.tv) ===")

    import_mode = get_plex_user_import_mode(db)

    log.info(
        f"[SYNC USERS] using import_mode={import_mode} "
        f"for entire synchronization run"
    )

    log.info(
        f"[SYNC USERS] plex_user_import_mode={import_mode}"
    )

    # ----------------------------------------------------
    # 1) Récupérer TOUS les serveurs Plex avec token
    #    (PAS de dédupe par token : on exécute /api/users par serveur)
    # ----------------------------------------------------
    server_rows = db.query(
        """
        SELECT id, name, token, server_identifier, status, cooldown_until
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
        srv = dict(srv)

        if should_skip_unreachable_server(srv):
            log.info(
                f"[SYNC USERS] skipped Plex server={srv.get('name')} "
                f"id={srv.get('id')} because it is down or in cooldown"
            )
            continue
        token = (srv["token"] or "").strip()

        if not token:
            log.warning(
                f"[SYNC USERS] {srv['name']}: missing Plex token"
            )
            continue

        machine_identifier = (
            srv["server_identifier"] or ""
        ).strip()

        if import_mode == "shared_only":
            log.info(
                f"[SYNC USERS] server #{idx}/{len(server_rows)}: "
                f"{srv['name']} (server_id={srv['id']}) -> /shared_servers"
            )

            data = fetch_shared_server_users(
                token=token,
                machine_identifier=machine_identifier,
                db=db
            )

        else:
            log.info(
                f"[SYNC USERS] server #{idx}/{len(server_rows)}: "
                f"{srv['name']} (server_id={srv['id']}) -> /api/users"
            )

            data = fetch_users_from_plex_api(token, db=db)
        if not data:
            endpoint_name = (
                "/shared_servers"
                if import_mode == "shared_only"
                else "/api/users"
            )

            log.warning(
                f"[SYNC USERS] {srv['name']}: {endpoint_name} returned no data | "
                f"server_id={srv['id']} | "
                f"machine_identifier={machine_identifier or 'missing'} | "
                f"token_present={'yes' if token else 'no'}"
            )

            continue

        servers_ok += 1
        log.info(f"[SYNC USERS] {srv['name']}: {len(data)} retrieved user(s)")

        for plex_id, u in data.items():
            if plex_id in users_data:
                users_data[plex_id] = merge_user(users_data[plex_id], u)
            else:
                users_data[plex_id] = u

    if not users_data:
        log.warning(
            "[SYNC USERS] Plex.tv returned no users for all servers. "
            "Keeping existing database state and skipping destructive sync."
        )
        return

    log.info(
        f"[SYNC USERS] /api/users global MERGE: {len(users_data)} uniques user(s) "
        f"(serveurs_ok={servers_ok}/{len(server_rows)})"
    )

    # ----------------------------------------------------
    # 3.b) Owner par serveur (server_id -> owner_plex_id)
    # ----------------------------------------------------
    owner_plex_id_by_server_id: Dict[int, str] = {}

    for srv in server_rows:
        srv = dict(srv)

        if should_skip_unreachable_server(srv):
            continue
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
            row = db.query_one("SELECT id FROM vodum_users WHERE email = ?", (email,))
            if row:
                vodum_user_id = row["id"]
                db.execute(
                    "UPDATE vodum_users SET username = COALESCE(username, ?) WHERE id = ?",
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
                    },
                    "plex_user": {
                        "subscription_active": data.get("subscription_active"),
                        "subscription_status": data.get("subscription_status"),
                        "subscription_plan": data.get("subscription_plan"),
                        "joined_at": data.get("joined_at"),
                        "accepted_at": data.get("accepted_at"),
                        "username": data.get("username"),
                        "email": data.get("email"),
                        "avatar": data.get("avatar"),
                    },
                    "plex_invite_state": plex_invite_state_payload("friend"),
                },
                ensure_ascii=False
            )

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

            pending_mu = db.query_one(
                """
                SELECT id
                FROM media_users
                WHERE server_id = ?
                  AND type = 'plex'
                  AND COALESCE(NULLIF(TRIM(external_user_id), ''), '') = ''
                  AND COALESCE(NULLIF(TRIM(accepted_at), ''), '') = ''
                  AND (
                    vodum_user_id = ?
                    OR (? <> '' AND lower(COALESCE(email, '')) = lower(?))
                    OR (? <> '' AND lower(COALESCE(username, '')) = lower(?))
                  )
                ORDER BY id ASC
                LIMIT 1
                """,
                (server_id, vodum_user_id, email or "", email or "", username or "", username or ""),
            )

            if row_mu and pending_mu and int(row_mu["id"]) != int(pending_mu["id"]):
                merge_accepted_plex_media_user(
                    db,
                    accepted_id=row_mu["id"],
                    pending_id=pending_mu["id"],
                )
                log.info(
                    f"[SYNC USERS] Removed accepted Plex invite duplicate id={pending_mu['id']} "
                    f"in favor of media_user id={row_mu['id']}"
                )
            elif not row_mu and pending_mu:
                row_mu = pending_mu
                log.info(
                    f"[SYNC USERS] Reconciled pending Plex invite media_user id={row_mu['id']} "
                    f"with accepted plex_id={plex_id}"
                )

            if row_mu:
                db.execute(
                    """
                    UPDATE media_users
                    SET vodum_user_id   = ?,
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
                    (
                        vodum_user_id,
                        plex_id,
                        username,
                        email,
                        avatar,
                        role_for_server,
                        joined_at,
                        accepted_at,
                        details_json,
                        row_mu["id"],
                    ),
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
                    (
                        server_id,
                        vodum_user_id,
                        plex_id,
                        username,
                        email,
                        avatar,
                        role_for_server,
                        joined_at,
                        accepted_at,
                        details_json,
                    ),
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
    if db is None:
        raise RuntimeError("sync_all() doit recevoir un DBManager")

    log.info("=== [SYNC ALL] Starting Plex synchronization ===")
    result = sync_all_servers(
        db,
        ensure_server_identity=_ensure_plex_server_identity,
        sync_users=sync_users_from_api,
        get_libraries=plex_get_libraries,
        sync_libraries=sync_plex_libraries,
        sync_owner=sync_plex_owner_for_server,
        find_base_url=_find_working_plex_base_url,
        sync_user_access=sync_plex_user_library_access,
    )
    if not result["success"]:
        if result["skipped_unreachable"] == result["server_count"]:
            log.warning("[SYNC ALL] All Plex servers are down or in cooldown; sync skipped.")
            return
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
    if is_debug_mode_enabled():
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
