
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Tuple, Optional

import requests
import xml.etree.ElementTree as ET
import json

from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import task_logs
from plexapi.server import PlexServer  
from core.plex_rate_limit import install_plex_rate_limit, wait_for_plex_slot
from core.plex_connection import plex_candidate_base_urls, find_working_plex_base_url
from core.server_cooldown import should_skip_unreachable_server, mark_server_unreachable, clear_server_cooldown
from core.http_security import ConfiguredHostSession, plex_server_http_session, url_origin
from core.providers.plex_invitation_state import (
    merge_accepted_plex_media_user,
    plex_invite_state_payload,
)

class TimeoutSession(requests.Session):
    """Session requests qui force un timeout par dÃ©faut."""
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


def get_plex_user_import_mode(db) -> str:
    row = db.query_one(
        "SELECT plex_user_import_mode FROM settings LIMIT 1"
    )

    if not row:
        return "global"

    value = str(row["plex_user_import_mode"] or "global").strip().lower()

    if value not in ("global", "shared_only"):
        return "global"

    return value


def _row_value(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def _json_dict_or_empty(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_pending_plex_invite_media_user(row) -> bool:
    """
    True si le media_user Plex correspond Ã  une invitation encore non acceptÃ©e.
    """
    accepted_at = str(_row_value(row, "accepted_at") or "").strip()
    if accepted_at:
        return False

    details = _json_dict_or_empty(_row_value(row, "details_json"))
    invite_state = details.get("plex_invite_state") or {}
    if isinstance(invite_state, dict) and bool(invite_state.get("is_pending")):
        return True

    external_user_id = str(_row_value(row, "external_user_id") or "").strip()
    email = str(_row_value(row, "email") or "").strip()
    username = str(_row_value(row, "username") or "").strip()

    # Fallback robuste :
    # user crÃ©Ã© cÃ´tÃ© Vodum, mais pas encore rÃ©ellement acceptÃ©/rÃ©solu cÃ´tÃ© Plex
    return (not accepted_at) and (not external_user_id) and bool(email or username)

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
        f"[SUBSCRIPTION] expiration_date initialized for vodum_user_id={vodum_user_id} â†’ {expiration}"
    )

    return True




# ---------------------------------------------------------------------------
# Token Plex.tv (pris dans la table servers)
# ---------------------------------------------------------------------------
def choose_account_token(db) -> Optional[str]:
    """
    Retourne un token Plex trouvÃ© dans la table 'servers'.
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
    Force la rÃ©cupÃ©ration du vrai machineIdentifier Plex avant sync_users_from_api().
    Sans Ã§a, un serveur fraÃ®chement ajoutÃ© garde l'UUID temporaire VODUM,
    et les users Plex rÃ©cupÃ©rÃ©s via /api/users ne peuvent pas Ãªtre reliÃ©s au bon serveur.
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
# RÃ©cupÃ©ration Owner Plex
# ---------------------------------------------------------------------------
def sync_plex_owner_for_server(db, server):
    """
    Synchronise le OWNER du serveur Plex donnÃ©.
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
    # 1) RÃ©soudre / crÃ©er le vodum_user (GLOBAL)
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
            db.execute(
                "UPDATE vodum_users SET username = COALESCE(username, ?) WHERE id = ?",
                (username, int(vodum_user_id)),
            )
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

    # identitÃ© plex globale
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

    # âœ… Forcer options UI/logique pour l'owner
    # (cochÃ©es dans l'UI, filtres vides par dÃ©faut)
    owner_plex_share = {
        "allowSync": 1,
        "allowCameraUpload": 1,
        "allowChannels": 1,
        "filterMovies": "",
        "filterTelevision": "",
        "filterMusic": "",
    }

    if row:
        # Merge safe du JSON existant (ne pas casser d'autres clÃ©s)
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

    # Force expiration override for Plex owner
    db.execute(
        """
        UPDATE vodum_users
        SET expiration_date_override = 1
        WHERE id = ?
        """,
        (vodum_user_id,),
    )
    if is_debug_mode_enabled():
        log.debug(
            f"[OWNER] {server['name']}: owner OK "
            f"(plex_id={plex_id}, vodum_user_id={vodum_user_id})"
        )



# ---------------------------------------------------------------------------
# RÃ©cupÃ©ration Libraries Plex (JSON local API)
# ---------------------------------------------------------------------------
def plex_get_user_access(db, plex, server_name, media_user_id: int):
    """
    Retourne les bibliothÃ¨ques rÃ©ellement partagÃ©es
    avec un utilisateur Plex (media_users).

    Retour :
    - list[dict] => accÃ¨s rÃ©cupÃ©rÃ© correctement
    - []         => accÃ¨s rÃ©cupÃ©rÃ© correctement mais aucune bibliothÃ¨que
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

def _plex_section_total_items(session, base_url: str, token: str, section_id: str, timeout: int = 10) -> int | None:
    # Astuce Plex: demander 0 item renvoie totalSize dans MediaContainer
    url = f"{base_url.rstrip('/')}/library/sections/{section_id}/all"
    r = session.get(
        url,
        headers={"X-Plex-Token": token},
        params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
        timeout=timeout,
    )
    r.raise_for_status()

    root = ET.fromstring(r.text)

    # Plex renvoie gÃ©nÃ©ralement <MediaContainer ...> en racine
    mc = root if root.tag == "MediaContainer" else root.find("MediaContainer")
    if mc is None:
        return None

    total = mc.attrib.get("totalSize") or mc.attrib.get("size")
    try:
        return int(total)
    except Exception:
        return None

def _get_media_user_library_ids_for_server(db, media_user_id: int, server_id: int) -> set[int]:
    rows = db.query(
        """
        SELECT mul.library_id
        FROM media_user_libraries mul
        JOIN libraries l ON l.id = mul.library_id
        WHERE mul.media_user_id = ?
          AND l.server_id = ?
        """,
        (media_user_id, server_id),
    ) or []

    return {int(r["library_id"]) for r in rows if r["library_id"] is not None}


def _apply_media_user_library_diff_for_server(
    db,
    media_user_id: int,
    server_id: int,
    desired_library_ids: set[int],
):
    current_library_ids = _get_media_user_library_ids_for_server(db, media_user_id, server_id)

    to_add = sorted(desired_library_ids - current_library_ids)
    to_remove = sorted(current_library_ids - desired_library_ids)

    for lib_id in to_add:
        db.execute(
            """
            INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
            VALUES (?, ?)
            """,
            (media_user_id, lib_id),
        )

    for lib_id in to_remove:
        db.execute(
            """
            DELETE FROM media_user_libraries
            WHERE media_user_id = ?
              AND library_id = ?
            """,
            (media_user_id, lib_id),
        )

    return current_library_ids, to_add, to_remove

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

    # 2ï¸âƒ£ Users liÃ©s Ã  ce serveur
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

    # 3ï¸âƒ£ Resync accÃ¨s pour chaque user
    for u in users:
        email = u["email"]
        media_user_id = u["media_user_id"]
        vodum_user_id = u["vodum_user_id"]
        role = (u["role"] or "").strip().lower()
        username = _row_value(u, "username", "")

        processed_users += 1

        # âœ… Ignore users that should no longer exist on Plex
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

        # âœ… Cas spÃ©cial : invitation Plex pas encore acceptÃ©e
        # On NE TOUCHE PAS aux media_user_libraries dÃ©jÃ  prÃ©vues en DB.
        if role != "owner" and _is_pending_plex_invite_media_user(u):
            preserved_pending += 1
            log.info(
                f"[SYNC ACCESS] Pending Plex invite preserved for user={username!r} "
                f"(media_user_id={media_user_id}, server={server_name})"
            )
            continue

        # âœ… Cas spÃ©cial : job Plex encore en attente / en cours
        # On SKIP complÃ¨tement cet utilisateur pour Ã©viter qu'un DELETE brutal
        # efface un Ã©tat qui doit encore Ãªtre appliquÃ© par apply_plex_access_updates.
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

        # âœ… OWNER : toutes les libraries du serveur
        if role == "owner":
            desired_library_ids = {int(lib_id) for lib_id in lib_map.values()}
            has_access = bool(desired_library_ids)

        else:
            # logique normale basÃ©e sur l'API Plex
            if not email:
                skipped_no_email += 1
                continue

            access = plex_get_user_access(db, plex, server_name, media_user_id)

            # âš ï¸ Si Plex rÃ©pond mal / erreur API, on ne supprime rien
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

        # âœ… uniquement si accÃ¨s rÃ©el trouvÃ©
        updated_users += 1

    log.info(
        f"[SYNC ACCESS] Access updated for server {server_name} "
        f"(users en base={len(users)}, traitÃ©s={processed_users}, maj={updated_users}, "
        f"sans_email={skipped_no_email}, pending_preserved={preserved_pending}, "
        f"sync_skipped_pending_jobs={skipped_pending_jobs})"
    )






def plex_get_libraries(server):
    """
    RÃ©cupÃ¨re la liste des libraries dâ€™un serveur Plex.
    Retourne :
    [
        {"section_id": "1", "name": "Films", "type": "movie"},
        ...
    ]
    """
    base_url = _find_working_plex_base_url(server, endpoint="/library/sections", accept="application/json")
    token = (server.get("token") or "").strip()

    if not base_url or not token:
        log.error(f"[SYNC LIBRARIES] Server {server['name']} without URL or token.")
        return []

    url = f"{base_url}/library/sections"
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
    }

    try:
        wait_for_plex_slot(base_url)
        resp = plex_server_http_session(server).get(url, headers=headers, timeout=30)
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
    Synchronise les libraries Plex pour un serveur donnÃ©.
    + met Ã  jour item_count.
    + rÃ©concilie une library existante si le section_id a changÃ©
      mais que server_id + name + type correspondent.
    """
    server_id = server["id"]

    base_url = _find_working_plex_base_url(
        server,
        endpoint="/library/sections",
        accept="application/json",
    )
    token = (server.get("token") or "").strip()

    rows = db.query(
        """
        SELECT id, section_id, name, type
        FROM libraries
        WHERE server_id = ?
        """,
        (server_id,),
    )

    rows = [dict(row) for row in rows]

    def _norm(v):
        return (str(v or "")).strip().casefold()

    # Match principal = vrai section_id Plex
    existing_by_section = {
        str(row["section_id"]): dict(row)
        for row in rows
        if str(row.get("section_id") or "").strip()
    }

    # Match de secours = mÃªme serveur + mÃªme nom + mÃªme type
    # On ne garde qu'une seule entrÃ©e par clÃ© ; si doublon dÃ©jÃ  prÃ©sent en base,
    # on prend la premiÃ¨re et on loggue.
    existing_by_identity = {}
    for row in rows:
        key = (_norm(row.get("name")), _norm(row.get("type")))
        if key not in existing_by_identity:
            existing_by_identity[key] = dict(row)
        else:
            log.warning(
                f"[SYNC LIBRARIES] Duplicate library identity already in DB for "
                f"server_id={server_id}, name={row.get('name')}, type={row.get('type')} "
                f"(ids {existing_by_identity[key]['id']} and {row['id']})"
            )

    found_ids = set()
    found_section_ids = set()

    session = plex_server_http_session(server)
    install_plex_rate_limit(session, base_url)

    for lib in libraries:
        sid = str(lib.get("section_id") or "").strip()
        name = (lib.get("name") or "").strip()
        ltype = (lib.get("type") or "unknown").strip()

        if not sid:
            log.warning(f"[SYNC LIBRARIES] Skipped library without section_id on server_id={server_id}: {lib}")
            continue

        identity_key = (_norm(name), _norm(ltype))
        matched_row = None

        # 1) Cas nominal : on retrouve la library par section_id
        if sid in existing_by_section:
            matched_row = existing_by_section[sid]

            db.execute(
                """
                UPDATE libraries
                SET name = ?, type = ?
                WHERE id = ?
                """,
                (name, ltype, matched_row["id"]),
            )

        else:
            # 2) Cas de rÃ©conciliation : mÃªme name + mÃªme type sur le mÃªme serveur
            candidate = existing_by_identity.get(identity_key)

            if candidate:
                old_sid = str(candidate.get("section_id") or "").strip()

                db.execute(
                    """
                    UPDATE libraries
                    SET section_id = ?, name = ?, type = ?
                    WHERE id = ?
                    """,
                    (sid, name, ltype, candidate["id"]),
                )

                matched_row = dict(candidate)
                matched_row["section_id"] = sid
                matched_row["name"] = name
                matched_row["type"] = ltype

                log.info(
                    f"[SYNC LIBRARIES] Reattached library id={candidate['id']} "
                    f"server_id={server_id} name={name!r} type={ltype!r} "
                    f"section_id {old_sid!r} -> {sid!r}"
                )

                # On met Ã  jour les index en mÃ©moire pour Ã©viter toute confusion
                if old_sid and old_sid in existing_by_section:
                    existing_by_section.pop(old_sid, None)
                existing_by_section[sid] = matched_row
                existing_by_identity[identity_key] = matched_row

            else:
                # 3) Vraie nouvelle library
                db.execute(
                    """
                    INSERT INTO libraries(server_id, section_id, name, type)
                    VALUES (?, ?, ?, ?)
                    """,
                    (server_id, sid, name, ltype),
                )

                inserted = db.query_one(
                    """
                    SELECT id, section_id, name, type
                    FROM libraries
                    WHERE server_id = ? AND section_id = ?
                    """,
                    (server_id, sid),
                )

                if inserted:
                    matched_row = dict(inserted)
                    existing_by_section[sid] = matched_row
                    existing_by_identity[identity_key] = matched_row
                    log.info(
                        f"[SYNC LIBRARIES] New library inserted id={inserted['id']} "
                        f"server_id={server_id} section_id={sid!r} name={name!r} type={ltype!r}"
                    )
                else:
                    log.warning(
                        f"[SYNC LIBRARIES] Inserted library not found back "
                        f"server_id={server_id} section_id={sid!r} name={name!r} type={ltype!r}"
                    )

        if matched_row:
            found_ids.add(int(matched_row["id"]))
        found_section_ids.add(sid)

        # item_count (best effort)
        if base_url and token:
            try:
                count = _plex_section_total_items(session, base_url, token, sid, timeout=10)
            except Exception:
                count = None

            if count is not None:
                db.execute(
                    "UPDATE libraries SET item_count = ? WHERE server_id = ? AND section_id = ?",
                    (int(count), server_id, sid),
                )

    # Suppression des vraies libraries disparues :
    # uniquement celles du serveur qui n'ont Ã©tÃ© ni revues ni rÃ©attachÃ©es.
    for row in rows:
        lib_id = int(row["id"])
        sid = str(row.get("section_id") or "").strip()

        if lib_id in found_ids:
            continue

        log.info(
            f"[SYNC LIBRARIES] Library removal id={lib_id} "
            f"(server_id={server_id}, section={sid!r}, name={row.get('name')!r}, type={row.get('type')!r})"
        )

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

    if is_debug_mode_enabled():
        log.debug(f"[API] GET {url}")

    try:
        session = ConfiguredHostSession(
            {url_origin("https://plex.tv")},
            default_timeout=20,
        )
        resp = session.get(url, headers=headers)
    except Exception as e:
        log.error(f"[API] Network error on {url}: {e}")
        return None

    if resp.status_code != 200:
        log.error(f"[API] {url} â†’ HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        root = ET.fromstring(resp.content)
        return root
    except Exception as e:
        log.error(f"[API] Invalid XML for {url}: {e}")
        return None

def fetch_admin_account_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    RÃ©cupÃ¨re le compte Plex liÃ© au token (owner/admin) via Plex.tv /users/account.
    Renvoie un dict au mÃªme format que fetch_users_from_plex_api() (sans servers).
    """
    url = "https://plex.tv/users/account"
    root = fetch_xml(url, token)
    if root is None:
        log.error("[API] Unable to retrieve /users/account")
        return None

    # Selon les rÃ©ponses Plex, Ã§a peut Ãªtre <user ...> ou autre, on prend les attribs
    plex_id = root.get("id")
    if not plex_id:
        log.error("[API] /users/account does not contain an ID")
        return None

    username = root.get("username") or root.get("title") or f"user_{plex_id}"
    email = (root.get("email") or "").strip() or None

    # Lâ€™attribut le plus courant est "thumb"
    avatar = root.get("thumb") or root.get("avatar")

    return {
        "plex_id": str(plex_id),
        "username": username,
        "email": email,
        "avatar": avatar,

        # On marque distinctement, tu trieras aprÃ¨s
        "plex_role": "owner",

        # Flags inconnus ici, on met 0 par dÃ©faut
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
        log.error("[API] Unable to retrieve /api/users â†’ Aborted.")
        return {}

    log.info("[API] /api/users Retrieved, parsingâ€¦")

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
        # RÃ´le Plex
        # ------------------------
        email_lower = email.lower() if email else ""

        if home_flag:
            plex_role = "home"
        else:
            plex_role = "friend"

        # ------------------------
        # Serveurs liÃ©s
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

        if is_debug_mode_enabled():
            log.debug(
                f"[API] User plex_id={plex_id} username={username!r} "
                f"role={plex_role}, servers={len(servers)}"
            )

    log.info(f"[API] /api/users â†’ {len(users)} User(s) retrieved.")
    return users


def fetch_shared_server_users(
    token: str,
    machine_identifier: str,
    db=None
) -> Dict[str, Dict[str, Any]]:

    result = {}

    if not token or not machine_identifier:
        return result

    session = ConfiguredHostSession(
        {url_origin("https://plex.tv")},
        default_timeout=20,
    )

    url = f"https://plex.tv/api/servers/{machine_identifier}/shared_servers"

    try:
        response = session.get(url, headers={"X-Plex-Token": token})
        response.raise_for_status()

        root = ET.fromstring(response.content)

        for shared in root.findall("SharedServer"):

            plex_id = str(
                shared.attrib.get("userID")
                or shared.attrib.get("userId")
                or shared.attrib.get("id")
                or ""
            ).strip()

            if not plex_id:
                continue

            username = (
                shared.attrib.get("username")
                or shared.attrib.get("title")
                or shared.attrib.get("name")
                or f"plex_{plex_id}"
            )

            email = shared.attrib.get("email") or None

            thumb = (
                shared.attrib.get("thumb")
                or shared.attrib.get("avatar")
                or ""
            )

            home = str(
                shared.attrib.get("home")
                or "0"
            ).lower() in ("1", "true")

            restricted = str(
                shared.attrib.get("restricted")
                or "0"
            ).lower() in ("1", "true")

            allow_sync = str(
                shared.attrib.get("allowSync")
                or "0"
            ).lower() in ("1", "true")

            result[plex_id] = {
                "plex_id": plex_id,
                "username": username,
                "email": email,
                "avatar": thumb,
                "plex_role": "friend",
                "home": home,
                "protected": False,
                "restricted": restricted,
                "allow_sync": allow_sync,
                "allow_camera_upload": False,
                "allow_channels": False,
                "joined_at": shared.attrib.get("invitedAt"),
                "accepted_at": shared.attrib.get("acceptedAt"),
                "servers": [
                    {
                        "machineIdentifier": machine_identifier
                    }
                ]
            }




    except Exception as e:
        body_preview = ""

        try:
            body_preview = response.text[:500]
        except Exception:
            pass

        log.error(
            f"[SYNC USERS] shared_servers failed | "
            f"machine_identifier={machine_identifier} | "
            f"url={url} | "
            f"error={e} | "
            f"response_preview={body_preview}"
        )

    return result


# ---------------------------------------------------------------------------
# Sync USERS + user_servers (Ã  partir de /api/users)
# ---------------------------------------------------------------------------
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
    # 1) RÃ©cupÃ©rer TOUS les serveurs Plex avec token
    #    (PAS de dÃ©dupe par token : on exÃ©cute /api/users par serveur)
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
    # 2) Mapping serveurs Plex (machineIdentifier â†’ id)
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
        # IdentitÃ© : garder le plus complet
        for k in ("username", "email", "avatar"):
            if not (dst.get(k) or "").strip():
                dst[k] = src.get(k)

        # Flags : garder le plus "vrai"
        for k in ("home", "protected", "restricted",
                  "allow_sync", "allow_camera_upload", "allow_channels"):
            if src.get(k) and not dst.get(k):
                dst[k] = src.get(k)

        # RÃ´le : home > friend > unknown (on ne force PAS owner ici)
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
    # 4) Upsert vodum_users + media_users (IDENTIQUE Ã  ton code)
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
                # ðŸ”¥ log crucial : tu verras immÃ©diatement quel machineIdentifier ne matche pas ta DB
                log.warning(
                    f"[SYNC USERS] machineIdentifier not mapped in the database: {machine_id} "
                    f"(user plex_id={plex_id}, username={username!r})"
                )
                continue

            seen_media_pairs.add((plex_id, server_id))

            # RÃ´le PAR SERVEUR (source de vÃ©ritÃ©)
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
    """
    Synchronisation complÃ¨te Plex :

      - Synchronise les utilisateurs Plex (crÃ©ation/MAJ media_users)
      - Synchronise les libraries Plex
      - Synchronise les accÃ¨s users â†’ libraries

    IMPORTANT :
      - DBManager uniquement
      - aucun commit / rollback
      - aucune ouverture / fermeture DB
    """

    if db is None:
        raise RuntimeError("sync_all() doit recevoir un DBManager")

    log.info("=== [SYNC ALL] Starting Plex synchronization ===")

    #
    # 1) RÃ©cupÃ©ration des serveurs Plex
    #
    servers = db.query(
        "SELECT * FROM servers WHERE type='plex'"
    )

    #
    # 2) RafraÃ®chir les vrais machineIdentifier Plex AVANT sync_users_from_api()
    #
    for server in servers:
        server = dict(server)
        if should_skip_unreachable_server(server):
            log.info(
                f"[SYNC IDENTITY] skipped Plex server={server.get('name')} "
                f"id={server.get('id')} because it is in cooldown"
            )
            continue

        _ensure_plex_server_identity(db, server)

    #
    # 3) Sync utilisateurs depuis Plex.tv (/api/users)
    #
    sync_users_from_api(db)

    if not servers:
        raise RuntimeError("No Plex server found in the database")

    any_success = False
    skipped_unreachable = 0

    #
    # 3) Pour chaque serveur â†’ sync libraries + accÃ¨s users
    #
    for server in servers:
        # IMPORTANT: sqlite3.Row -> dict, pour supporter .get() et Ã©viter les crash
        server = dict(server)

        server_name = server.get("name") or f"server_{server.get('id')}"
        if should_skip_unreachable_server(server):
            skipped_unreachable += 1
            log.info(
                f"[SYNC ALL] skipped Plex server={server_name} "
                f"id={server.get('id')} because it is down or in cooldown"
            )
            continue
        log.info(f"[SYNC ALL] Plex server: {server_name}")

        # --- Libraries ---
        try:
            libs = plex_get_libraries(server)
            sync_plex_libraries(db, server, libs)
            sync_plex_owner_for_server(db, server)

        except Exception as e:
            log.error(
                f"[SYNC LIBS] Library synchronization error for {server_name}: {e}",
                exc_info=is_debug_mode_enabled()
            )
            mark_server_unreachable(db, int(server["id"]), str(e), cooldown_seconds=300)
            continue

        # --- AccÃ¨s utilisateurs ---
        base_url = _find_working_plex_base_url(server, endpoint="/identity", accept="application/xml")
        token = (server.get("token") or "").strip()

        if not base_url or not token:
            reason = "No working Plex URL or missing token"
            log.warning(
                f"[SYNC ACCESS] Server {server_name} {reason} â†’ access ignored"
            )
            mark_server_unreachable(db, int(server["id"]), reason, cooldown_seconds=300)
            continue

        try:
            # ðŸ”Ž logs ciblage + garde-fou rÃ©seau
            log.info(f"[SYNC ACCESS] Attempting PlexAPI connection â†’ {server_name} base_url={base_url}")

            # â±ï¸ timeout forcÃ© pour plexapi
            session = plex_server_http_session(server, default_timeout=20)
            install_plex_rate_limit(session, base_url)

            # petit ping trÃ¨s parlant (et timeout)
            try:
                r = session.get(f"{base_url}/identity")
                log.info(f"[SYNC ACCESS] /identity OK ({server_name}) HTTP={r.status_code}")
            except Exception as e:
                log.error(f"[SYNC ACCESS] /identity KO ({server_name}) : {e}")
                raise

            plex = PlexServer(base_url, token, session=session)

            log.info(f"[SYNC ACCESS] PlexAPI connected ({server_name}) â†’ Starting user access synchronization")

            sync_plex_user_library_access(db, plex, server)

            db.execute(
                """
                UPDATE servers
                SET status='up',
                    last_checked=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (int(server["id"]),),
            )
            clear_server_cooldown(db, int(server["id"]))

            log.info(f"[SYNC ACCESS] User access synchronization completed ({server_name})")

            any_success = True

        except Exception as e:
            log.error(
                f"[SYNC ACCESS] Connection or synchronization failed for {server_name}: {e}",
                exc_info=is_debug_mode_enabled()
            )
            mark_server_unreachable(db, int(server["id"]), str(e), cooldown_seconds=300)
            continue


    if not any_success:
        if skipped_unreachable == len(servers):
            log.warning("[SYNC ALL] All Plex servers are down or in cooldown; sync skipped.")
            return
        raise RuntimeError("No Plex server could be synchronized")

    log.info("=== [SYNC ALL] Plex synchronization completed ===")




# ---------------------------------------------------------------------------
# API POUR LE SCHEDULER (tasks_engine)
# ---------------------------------------------------------------------------
def run(task_id: int, db):
    """
    Point d'entrÃ©e pour le scheduler VODUM.
    """

    log.info("=== [SYNC_PLEX] sync_plex task started ===")
    if is_debug_mode_enabled():
        log.debug(f"[SYNC_PLEX] task_id={task_id}")

    task_logs(task_id, "info", "Plex synchronization startedâ€¦")

    start = time.monotonic()

    try:
        sync_all(task_id, db=db)

        duration = time.monotonic() - start
        log.info(f"=== [SYNC_PLEX] Completed successfully in {duration:.2f}s ===")

        # ðŸ”¥ nouvelle vÃ©rification
        if db.query_one("SELECT 1 FROM media_users LIMIT 1"):
            task_logs(task_id, "success", "Plex synchronization completed successfully.")
        else:
            task_logs(task_id, "info", "Plex synchronization completed â€” no users found.")

    except Exception as e:
        duration = time.monotonic() - start
        log.error(
            f"=== [SYNC_PLEX] FAILED after {duration:.2f}s ===",
            exc_info=True,
        )
        task_logs(task_id, "error", f"Error during sync_plex : {e}")
        raise

