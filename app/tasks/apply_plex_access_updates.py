import json
from datetime import datetime, timedelta
from plexapi.server import PlexServer
from logging_utils import get_logger
import xml.etree.ElementTree as ET
from plexapi.exceptions import BadRequest
from core.providers.plex_users import plex_invite_and_share
import re
import requests
from core.plex_rate_limit import install_plex_rate_limit
from core.plex_connection import find_working_plex_base_url
from core.server_cooldown import should_skip_unreachable_server
from core.http_security import plex_server_http_session
from core.plex_access_identity import (
    PendingPlexInvite,
    resolve_plex_user,
    row_get,
    sync_media_user_identity_from_plex,
)
from core.plex_access_jobs import (
    cleanup_old_jobs,
    get_plex_share_settings_from_user as _get_plex_share_settings_from_user,
    is_owner_media_user,
    resolve_media_user,
)
from core.plex_access_runtime import (
    install_plex_http_logger,
    log_updatefriend_payload,
)

logger = get_logger("apply_plex_access_updates")

def resolve_or_repair_plex_user(db, server_row, user_row, sections_for_repair):
    """
    Résout un user Plex sans jamais lancer d'invitation/réinvitation automatique
    pendant une simple tâche d'accès aux bibliothèques.
    """
    plex = get_plex(server_row)
    account = plex.myPlexAccount()
    install_plex_http_logger(getattr(account, "_session", None), "PLEX_ACCOUNT")

    try:
        plex_user = resolve_plex_user(account, user_row)
        sync_media_user_identity_from_plex(db, user_row, plex_user)
        refreshed = db.query_one(
            "SELECT id, server_id, vodum_user_id, external_user_id, username, email, avatar, stored_password, type, role, joined_at, accepted_at, raw_json, details_json FROM media_users WHERE id = ?",
            (row_get(user_row, "id"),),
        )
        return plex, account, refreshed or user_row, plex_user

    except PendingPlexInvite:
        raise

    except Exception:
        logger.exception(
            "[PLEX RESOLVE] unable to resolve user without re-inviting "
            f"media_user_id={row_get(user_row, 'id')!r} "
            f"username={row_get(user_row, 'username')!r} "
            f"email={row_get(user_row, 'email')!r} "
            f"server={row_get(server_row, 'name')!r}"
        )
        raise

def get_plex(server_row):
	"""Connexion PlexAPI avec sélection automatique de la bonne URL Plex."""
	baseurl = find_working_plex_base_url(
		server_row,
		endpoint="/identity",
		accept="application/xml",
	)
	token = server_row["token"]

	if not baseurl or not token:
		raise RuntimeError(f"Incomplete server configuration (URL/token) : {server_row['name']}")

	session = plex_server_http_session(server_row)
	install_plex_rate_limit(session, baseurl)

	return PlexServer(baseurl, token, session=session)


def get_all_plex_section_titles(plex):
    """
    JBOPS: sections_lst = [x.title for x in plex.library.sections()]
    On récupère les TITRES réels côté Plex (le plus fiable).
    """
    try:
        return [s.title for s in plex.library.sections()]
    except Exception:
        logger.exception("❌ Unable to read plex.library.sections()")
        raise


def _plex_title_to_id_map(account, machine_id: str) -> dict:
    """
    Récupère un mapping {title -> id} depuis:
    GET https://plex.tv/api/servers/<machine_id>
    """
    url = f"https://plex.tv/api/servers/{machine_id}"
    resp = account.query(url, account._session.get)

    root = None
    if hasattr(resp, "findall"):
        root = resp
    else:
        try:
            root = ET.fromstring(resp)
        except Exception:
            raise RuntimeError("Unable to parse Plex server sections XML")

    m = {}
    for sec in root.findall(".//Section"):
        title = sec.attrib.get("title")
        sid = sec.attrib.get("id")
        if title and sid:
            m[title] = sid
    return m


def _find_shared_server_id_for_machine(plex_user, machine_id: str):
    """
    Retrouve le shared_server_id pour CE user sur CE serveur (machine_id).
    """
    for srv in (getattr(plex_user, "servers", None) or []):
        if getattr(srv, "machineIdentifier", None) == machine_id:
            return getattr(srv, "id", None)
    return None


def _get_shared_servers_for_machine(account, machine_id: str):
    """
    GET https://plex.tv/api/servers/<machine_id>/shared_servers
    Returns list of dicts: {id, username, email, userID, section_ids}
    """
    url = f"https://plex.tv/api/servers/{machine_id}/shared_servers"
    resp = account.query(url, account._session.get)

    if isinstance(resp, ET.Element):
        root = resp
    else:
        xml_text = None
        if hasattr(resp, "text") and isinstance(resp.text, str):
            xml_text = resp.text
        elif isinstance(resp, (str, bytes)):
            xml_text = resp.decode() if isinstance(resp, bytes) else resp
        else:
            try:
                xml_text = ET.tostring(resp).decode("utf-8")
            except Exception:
                xml_text = str(resp)

        root = ET.fromstring(xml_text)

    out = []
    for ss in root.findall(".//SharedServer"):
        section_ids = []

        raw_section_ids = (
            ss.attrib.get("librarySectionIDs")
            or ss.attrib.get("librarySectionIds")
            or ss.attrib.get("library_section_ids")
            or ""
        )
        for part in str(raw_section_ids).replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                section_ids.append(int(part))

        for child in list(ss):
            child_id = (
                child.attrib.get("id")
                or child.attrib.get("key")
                or child.attrib.get("librarySectionID")
                or child.attrib.get("librarySectionId")
            )
            if child_id and str(child_id).isdigit():
                section_ids.append(int(child_id))

        out.append(
            {
                "id": ss.attrib.get("id"),
                "username": ss.attrib.get("username"),
                "email": ss.attrib.get("email"),
                "userID": ss.attrib.get("userID") or ss.attrib.get("userId"),
                "invitedId": ss.attrib.get("invitedId") or ss.attrib.get("invitedID") or ss.attrib.get("invited_id"),
                "section_ids": sorted(set(section_ids)),
            }
        )

    return out


def _find_shared_server_id_for_user_on_machine(account, machine_id: str, plex_user_obj):
    """
    Retrouve le shared_server_id pour CE user sur CE serveur.
    Match robuste:
    - userID / invitedId
    - username
    - email
    - title (au cas où username soit vide côté objet Plex)
    Le tout en comparaison insensible à la casse.
    """
    def norm(v):
        return str(v or "").strip()

    def norm_lower(v):
        return norm(v).lower()

    target_uid = norm(getattr(plex_user_obj, "id", None))
    target_username = norm_lower(getattr(plex_user_obj, "username", None))
    target_email = norm_lower(getattr(plex_user_obj, "email", None))
    target_title = norm_lower(getattr(plex_user_obj, "title", None))

    shared = _get_shared_servers_for_machine(account, machine_id)

    for ss in shared:
        ss_id = ss.get("id")
        ss_uid = norm(ss.get("userID"))
        ss_invited = norm(ss.get("invitedId"))
        ss_username = norm_lower(ss.get("username"))
        ss_email = norm_lower(ss.get("email"))

        if target_uid and (ss_uid == target_uid or ss_invited == target_uid):
            return ss_id

        if target_username and ss_username == target_username:
            return ss_id

        if target_email and ss_email == target_email:
            return ss_id

        if target_title and ss_username == target_title:
            return ss_id

    return None

def _find_shared_server_state_for_user_on_machine(account, machine_id: str, plex_user_obj):
    """
    Retourne l'état Plex actuel du partage pour CE user sur CE serveur.
    Utilisé pour logger le diff réel avant modification.
    """
    shared_id = _find_shared_server_id_for_user_on_machine(account, machine_id, plex_user_obj)
    if not shared_id:
        return None

    for ss in _get_shared_servers_for_machine(account, machine_id):
        if str(ss.get("id") or "").strip() == str(shared_id):
            return ss

    return {"id": shared_id, "section_ids": []}


def _log_access_diff(action: str, *, vodum_user_id, media_user_id, server_id, machine_id, shared_server_id, current_section_ids, expected_section_ids):
    current = {int(x) for x in (current_section_ids or []) if str(x).isdigit()}
    expected = {int(x) for x in (expected_section_ids or []) if str(x).isdigit()}

    keep = sorted(current & expected)
    add = sorted(expected - current)
    remove = sorted(current - expected)

    logger.info(
        f"[PLEX ACCESS DIFF] action={action} "
        f"vodum_user_id={vodum_user_id} media_user_id={media_user_id} "
        f"server_id={server_id} machine_id={machine_id} "
        f"shared_server_id={shared_server_id} "
        f"keep={keep} add={add} remove={remove}"
    )

def _extract_already_shared_username(error_message: str) -> str | None:
    """
    Extrait le username depuis:
    "You're already sharing this server with adrienferret. Please edit your existing share."
    """
    msg = str(error_message or "")
    m = re.search(r"already sharing this server with\s+([^.<>]+)", msg, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip().lower() or None

def _ensure_shared_server(account, machine_id: str, plex_user_obj, section_ids: list):
    """
    Garantit que le share existe.
    - si trouvé => retourne son id
    - sinon tente création
    - si Plex répond "already sharing", on récupère l'id existant
      par username / email / id sans jamais réinviter
    """
    shared_id = _find_shared_server_id_for_user_on_machine(account, machine_id, plex_user_obj)
    if shared_id:
        return shared_id

    invited_id = getattr(plex_user_obj, "id", None)
    if not invited_id:
        raise RuntimeError("Cannot create share: plex_user.id missing")

    url = f"https://plex.tv/api/servers/{machine_id}/shared_servers"
    payload = {
        "server_id": str(machine_id),
        "shared_server": {
            "library_section_ids": [int(x) for x in section_ids],
            "invited_id": int(invited_id),
        },
    }

    try:
        resp = account.query(
            url,
            account._session.post,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    except BadRequest as e:
        msg = str(e)
        if "already sharing this server" in msg.lower():
            hinted_username = _extract_already_shared_username(msg)
            shared = _get_shared_servers_for_machine(account, machine_id)

            # 1) recherche par username explicitement retourné par Plex
            if hinted_username:
                for ss in shared:
                    ss_username = str(ss.get("username") or "").strip().lower()
                    ss_email = str(ss.get("email") or "").strip().lower()
                    if ss_username == hinted_username or ss_email == hinted_username:
                        if ss.get("id"):
                            logger.warning(
                                f"[PLEX SHARE RECOVER] existing share recovered from Plex error "
                                f"username={hinted_username!r} shared_server_id={ss.get('id')}"
                            )
                            return ss.get("id")

            # 2) nouvelle tentative avec le matching normal
            shared_id = _find_shared_server_id_for_user_on_machine(account, machine_id, plex_user_obj)
            if shared_id:
                logger.warning(
                    f"[PLEX SHARE RECOVER] existing share recovered after POST failure "
                    f"shared_server_id={shared_id}"
                )
                return shared_id

            # 3) on échoue proprement avec détails utiles
            sample = [
                {
                    "id": ss.get("id"),
                    "username": ss.get("username"),
                    "email": ss.get("email"),
                    "userID": ss.get("userID"),
                    "invitedId": ss.get("invitedId"),
                }
                for ss in shared[:10]
            ]
            raise RuntimeError(
                "Plex says the share already exists, but Vodum could not recover shared_server_id. "
                f"machine_id={machine_id!r}, "
                f"plex_user_id={getattr(plex_user_obj, 'id', None)!r}, "
                f"plex_username={getattr(plex_user_obj, 'username', None)!r}, "
                f"plex_email={getattr(plex_user_obj, 'email', None)!r}, "
                f"hinted_username={hinted_username!r}, "
                f"shared_sample={sample!r}"
            )

        raise

    xml_text = (
        resp.text
        if hasattr(resp, "text")
        else (resp.decode() if isinstance(resp, bytes) else str(resp))
    )
    try:
        root = ET.fromstring(xml_text)
        ss = root.find(".//SharedServer")
        if ss is not None and ss.attrib.get("id"):
            return ss.attrib.get("id")
    except Exception:
        pass

    shared_id = _find_shared_server_id_for_user_on_machine(account, machine_id, plex_user_obj)
    if not shared_id:
        raise RuntimeError("Share created but shared_server id still not found via plex.tv API")
    return shared_id


def _put_shared_server_form(account, machine_id: str, shared_server_id: str,
                            plex_user_obj,
                            section_ids: list,
                            allowSync: bool, allowCameraUpload: bool, allowChannels: bool,
                            filterMovies: str, filterTelevision: str, filterMusic: str):
    """
    PUT FORM body sur:
    https://plex.tv/api/servers/<machine_id>/shared_servers/<shared_server_id>

    ⚠️ IMPORTANT:
    Plex est instable sur les noms exacts des champs acceptés.
    Donc on envoie volontairement plusieurs variantes (flat + nested) pour que
    le serveur prenne au moins une des formes.
    """
    url = f"https://plex.tv/api/servers/{machine_id}/shared_servers/{shared_server_id}"
    invited_id = getattr(plex_user_obj, "id", None)

    def b01(v: bool) -> str:
        return "1" if v else "0"

    data = []

    # ---- flags / filters : flat ----
    data.extend([
        ("allowSync", b01(bool(allowSync))),
        ("allowCameraUpload", b01(bool(allowCameraUpload))),
        ("allowChannels", b01(bool(allowChannels))),
        ("filterMovies", str(filterMovies or "")),
        ("filterTelevision", str(filterTelevision or "")),
        ("filterMusic", str(filterMusic or "")),
    ])

    # ---- flags / filters : nested ----
    data.extend([
        ("shared_server[allowSync]", b01(bool(allowSync))),
        ("shared_server[allowCameraUpload]", b01(bool(allowCameraUpload))),
        ("shared_server[allowChannels]", b01(bool(allowChannels))),
        ("shared_server[filterMovies]", str(filterMovies or "")),
        ("shared_server[filterTelevision]", str(filterTelevision or "")),
        ("shared_server[filterMusic]", str(filterMusic or "")),
    ])

    # invited id (certaines variantes l'exigent)
    if invited_id is not None:
        data.append(("invited_id", str(int(invited_id))))
        data.append(("shared_server[invited_id]", str(int(invited_id))))

    # ---- libraries: envoyer plusieurs variantes ----
    for sid in section_ids:
        sid_str = str(int(sid))
        data.append(("librarySectionID[]", sid_str))
        data.append(("library_section_ids[]", sid_str))
        data.append(("shared_server[librarySectionID][]", sid_str))
        data.append(("shared_server[library_section_ids][]", sid_str))

    # IMPORTANT: forcer le content-type pour que requests encode correctement
    account.query(
        url,
        account._session.put,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def update_friend_safe(account, plex, username, sections, removeSections=False):
    """
    Wrapper anti-404 (conservé).
    """
    try:
        return account.updateFriend(
            user=username,
            server=plex,
            sections=sections,
            removeSections=removeSections,
        )
    except Exception as e:
        logger.warning(f"updateFriend() failed (likely Plex v2 sharings 404): {e}")
        logger.warning("Retry updateFriend() in LIBS-ONLY mode (no allow*/filters)")
        return account.updateFriend(
            user=username,
            server=plex,
            sections=sections,
            removeSections=removeSections,
        )


def apply_grant_job(db, job):
    """
    Ajoute une bibliothèque à un utilisateur Plex.
    Source de vérité = DB.
    API legacy /shared_servers + PUT form.
    """
    server_id = job["server_id"]
    lib_id = job["library_id"]
    vodum_user_id = job["vodum_user_id"]

    user = resolve_media_user(db, vodum_user_id, server_id, job=job)
    user_id = user["id"]

    if is_owner_media_user(user):
        logger.info(
            f"Skip GRANT (owner) : username={user['username']} server_id={server_id} library_id={lib_id}"
        )
        return

    server = db.query_one("SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE id=?", (server_id,))
    library = db.query_one("SELECT id, server_id, section_id, name, type, item_count FROM libraries WHERE id=?", (lib_id,))

    if not server:
        raise RuntimeError(f"Server not found (id={server_id})")
    if not library:
        raise RuntimeError(f"Library not found (id={lib_id})")

    logger.info(f"Updating access: {user['username']} ← {library['name']} sur {server['name']}")

    sections_for_repair = [library["name"]]

    try:
        plex, account, user, plex_user = resolve_or_repair_plex_user(
            db=db,
            server_row=server,
            user_row=user,
            sections_for_repair=sections_for_repair,
        )
        logger.info(
            "Plex debug user: "
            f"db_external_user_id='{row_get(user, 'external_user_id')}' "
            f"db_username='{user['username']}' "
            f"db_email='{row_get(user, 'email')}' "
            f"plex_id='{getattr(plex_user, 'id', None)}' "
            f"plex_username='{getattr(plex_user, 'username', None)}' "
            f"plex_email='{getattr(plex_user, 'email', None)}'"
        )
    except PendingPlexInvite as e:
        logger.info(str(e))
        raise
    except Exception:
        logger.exception(
            f"Unable to retrieve/repair MyPlexUser for username={user['username']} "
            f"external_user_id={row_get(user, 'external_user_id')} "
            f"email={row_get(user, 'email')}"
        )
        raise

    machine_id = plex.machineIdentifier

    rows = db.query(
        """
        SELECT l.name
        FROM media_user_libraries mul
        JOIN libraries l ON mul.library_id = l.id
        WHERE mul.media_user_id = ?
          AND l.server_id = ?
        """,
        (user_id, server_id),
    )
    sections = {row_get(r, "name") for r in rows if row_get(r, "name")}
    sections.add(library["name"])
    sections = sorted(sections)
    logger.info(f"Final sections sent: {sections}")

    (
        allowSync,
        allowCameraUpload,
        allowChannels,
        filterMovies,
        filterTelevision,
        filterMusic,
    ) = _get_plex_share_settings_from_user(user)

    log_updatefriend_payload(
        action="grant",
        server_row=server,
        user_row=user,
        plex_obj=plex,
        plex_user_obj=plex_user,
        sections=sections,
        allowSync=allowSync,
        allowCameraUpload=allowCameraUpload,
        allowChannels=allowChannels,
        filterMovies=filterMovies,
        filterTelevision=filterTelevision,
        filterMusic=filterMusic,
    )

    title_to_id = _plex_title_to_id_map(account, machine_id)
    missing = [t for t in sections if t not in title_to_id]
    if missing:
        logger.warning(f"Some sections are unknown on Plex server (ignored): {missing}")
    section_ids = [int(title_to_id[t]) for t in sections if t in title_to_id]
    if not section_ids:
        raise RuntimeError("No valid Plex section ids to grant (all titles missing on server)")

    shared_state = _find_shared_server_state_for_user_on_machine(account, machine_id, plex_user)
    shared_server_id = _ensure_shared_server(account, machine_id, plex_user, section_ids)
    if not shared_state or str(shared_state.get("id") or "") != str(shared_server_id):
        shared_state = _find_shared_server_state_for_user_on_machine(account, machine_id, plex_user)

    _log_access_diff(
        "grant",
        vodum_user_id=vodum_user_id,
        media_user_id=user_id,
        server_id=server_id,
        machine_id=machine_id,
        shared_server_id=shared_server_id,
        current_section_ids=(shared_state or {}).get("section_ids", []),
        expected_section_ids=section_ids,
    )

    _put_shared_server_form(
        account=account,
        machine_id=machine_id,
        shared_server_id=str(shared_server_id),
        plex_user_obj=plex_user,
        section_ids=section_ids,
        allowSync=allowSync,
        allowCameraUpload=allowCameraUpload,
        allowChannels=allowChannels,
        filterMovies=filterMovies,
        filterTelevision=filterTelevision,
        filterMusic=filterMusic,
    )

    logger.info("✅ GRANT applied via plex.tv legacy shared_servers API")


def apply_sync_job(db, job):
    """
    Synchronise TOUTES les bibliothèques autorisées (DB => Plex).
    API legacy /shared_servers + PUT form.
    """
    server_id = job["server_id"]
    vodum_user_id = job["vodum_user_id"]

    user = resolve_media_user(db, vodum_user_id, server_id, job=job)
    user_id = user["id"]

    if is_owner_media_user(user):
        logger.info(f"Skip SYNC (owner) : username={user['username']} server_id={server_id}")
        return

    server = db.query_one("SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE id=?", (server_id,))
    if not server:
        raise RuntimeError("Server not found (sync)")

    logger.info(
        f"FULL ACCESS SYNC: {user['username']} on {server['name']} "
        f"(server_id={server_id}, user_id={user_id})"
    )

    rows = db.query(
        """
        SELECT l.name
        FROM media_user_libraries mul
        JOIN libraries l ON mul.library_id = l.id
        WHERE mul.media_user_id = ?
          AND l.server_id = ?
        """,
        (user_id, server_id),
    )
    sections = [row_get(r, "name") for r in rows]
    sections = [s for s in sections if s]
    logger.info(f"Sections DB (expected) ({len(sections)}): {sections}")

    try:
        plex, account, user, plex_user = resolve_or_repair_plex_user(
            db=db,
            server_row=server,
            user_row=user,
            sections_for_repair=sections,
        )
        logger.info(
            "Plex debug user: "
            f"db_external_user_id='{row_get(user, 'external_user_id')}' "
            f"db_username='{user['username']}' "
            f"db_email='{row_get(user, 'email')}' "
            f"plex_id='{getattr(plex_user, 'id', None)}' "
            f"plex_username='{getattr(plex_user, 'username', None)}' "
            f"plex_email='{getattr(plex_user, 'email', None)}'"
        )
    except PendingPlexInvite as e:
        logger.info(str(e))
        raise
    except Exception:
        logger.exception(
            f"Unable to retrieve/repair MyPlexUser for username={user['username']} "
            f"external_user_id={row_get(user, 'external_user_id')} "
            f"email={row_get(user, 'email')}"
        )
        raise



    (
        allowSync,
        allowCameraUpload,
        allowChannels,
        filterMovies,
        filterTelevision,
        filterMusic,
    ) = _get_plex_share_settings_from_user(user)

    log_updatefriend_payload(
        action="sync",
        server_row=server,
        user_row=user,
        plex_obj=plex,
        plex_user_obj=plex_user,
        sections=sections,
        allowSync=allowSync,
        allowCameraUpload=allowCameraUpload,
        allowChannels=allowChannels,
        filterMovies=filterMovies,
        filterTelevision=filterTelevision,
        filterMusic=filterMusic,
    )

    machine_id = plex.machineIdentifier

    title_to_id = _plex_title_to_id_map(account, machine_id)
    missing = [t for t in sections if t not in title_to_id]
    if missing:
        logger.warning(f"Some sections are unknown on Plex server (ignored): {missing}")
    section_ids = [int(title_to_id[t]) for t in sections if t in title_to_id]

    if not section_ids:
        raise RuntimeError(
            "SYNC aborted: computed an empty Plex section list. "
            "Vodum will not convert a sync job into a full revoke. "
            "Use an explicit revoke job to remove all Plex access."
        )

    shared_state = _find_shared_server_state_for_user_on_machine(account, machine_id, plex_user)
    shared_server_id = _ensure_shared_server(account, machine_id, plex_user, section_ids)
    if not shared_state or str(shared_state.get("id") or "") != str(shared_server_id):
        shared_state = _find_shared_server_state_for_user_on_machine(account, machine_id, plex_user)

    _log_access_diff(
        "sync",
        vodum_user_id=vodum_user_id,
        media_user_id=user_id,
        server_id=server_id,
        machine_id=machine_id,
        shared_server_id=shared_server_id,
        current_section_ids=(shared_state or {}).get("section_ids", []),
        expected_section_ids=section_ids,
    )

    _put_shared_server_form(
        account=account,
        machine_id=machine_id,
        shared_server_id=str(shared_server_id),
        plex_user_obj=plex_user,
        section_ids=section_ids,
        allowSync=allowSync,
        allowCameraUpload=allowCameraUpload,
        allowChannels=allowChannels,
        filterMovies=filterMovies,
        filterTelevision=filterTelevision,
        filterMusic=filterMusic,
    )

    logger.info("✅ SYNC applied via plex.tv legacy shared_servers API")


def apply_revoke_job(db, job):
    """
    Retire TOUS les accès aux bibliothèques pour un utilisateur sur un serveur.
    DELETE /shared_servers/<id>
    """
    server_id = job["server_id"]
    vodum_user_id = job["vodum_user_id"]

    user = resolve_media_user(db, vodum_user_id, server_id, job=job)
    if is_owner_media_user(user):
        logger.info(f"Skip REVOKE (owner) : username={user['username']} server_id={server_id}")
        return

    server = db.query_one("SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE id=?", (server_id,))
    if not server:
        raise RuntimeError("Server not found (revoke)")

    try:
        plex, account, user, plex_user = resolve_or_repair_plex_user(
            db=db,
            server_row=server,
            user_row=user,
            sections_for_repair=[],
        )
    except PendingPlexInvite as e:
        logger.info(str(e))
        raise
    except Exception:
        logger.exception(
            f"Unable to retrieve/repair MyPlexUser for username={user['username']} "
            f"external_user_id={row_get(user, 'external_user_id')} "
            f"email={row_get(user, 'email')}"
        )
        raise

    machine_id = plex.machineIdentifier
    shared_server_id = _find_shared_server_id_for_user_on_machine(account, machine_id, plex_user)
    if not shared_server_id:
        logger.info("REVOKE: no existing share found (noop).")
        return

    shared_state = _find_shared_server_state_for_user_on_machine(account, machine_id, plex_user)
    _log_access_diff(
        "revoke",
        vodum_user_id=vodum_user_id,
        media_user_id=row_get(user, "id"),
        server_id=server_id,
        machine_id=machine_id,
        shared_server_id=shared_server_id,
        current_section_ids=(shared_state or {}).get("section_ids", []),
        expected_section_ids=[],
    )

    url = f"https://plex.tv/api/servers/{machine_id}/shared_servers/{shared_server_id}"
    account.query(url, account._session.delete)
    logger.info("✅ REVOKE applied via plex.tv legacy shared_servers API")


def run(task_id: int, db):
    logger.debug("=== APPLY PLEX ACCESS UPDATES : START ===")

    db.execute(
        """
        UPDATE media_jobs
        SET status = 'queued',
            locked_by = NULL,
            locked_until = NULL,
            last_error = COALESCE(last_error, 'Recovered stale running Plex access job')
        WHERE provider = 'plex'
          AND action IN ('grant','revoke','sync')
          AND status = 'running'
          AND locked_until IS NOT NULL
          AND locked_until <= CURRENT_TIMESTAMP
        """
    )

    jobs = db.query(
        """
        SELECT id, provider, action, vodum_user_id, server_id, library_id, payload_json, status, priority, run_after, locked_by, locked_until, attempts, max_attempts, last_error, processed, success, created_at, processed_at, executed_at, dedupe_key FROM media_jobs
        WHERE provider = 'plex'
          AND status = 'queued'
          AND processed = 0
          AND action IN ('grant','revoke','sync')
          AND (run_after IS NULL OR run_after <= CURRENT_TIMESTAMP)
          AND (locked_until IS NULL OR locked_until <= CURRENT_TIMESTAMP)
        ORDER BY priority ASC, id ASC
        LIMIT 50
        """
    )

    if not jobs:
        logger.debug("No jobs to process.")
        return {"processed": 0, "errors": 0}

    logger.info(f"{len(jobs)} job(s) to process...")

    processed = 0
    errors = 0

    for job in jobs:
        job_id = job["id"]
        server = db.query_one("SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE id=?", (job["server_id"],))
        if server and should_skip_unreachable_server(server):
            logger.info(
                f"Skipping Plex job id={job_id}: server_id={job['server_id']} is in cooldown"
            )
            continue
        locked_until = (datetime.utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

        claim = db.execute(
            """
            UPDATE media_jobs
            SET status = 'running',
                locked_by = ?,
                locked_until = ?,
                executed_at = datetime('now'),
                attempts = COALESCE(attempts, 0) + 1,
                last_error = NULL
            WHERE id = ?
              AND provider = 'plex'
              AND status = 'queued'
              AND processed = 0
            """,
            (f"apply_plex_access_updates:{task_id}", locked_until, job_id),
        )

        if getattr(claim, "rowcount", 0) == 0:
            logger.info(f"Job {job_id} already claimed by another worker, skipped.")
            continue

        job = db.query_one("SELECT id, provider, action, vodum_user_id, server_id, library_id, payload_json, status, priority, run_after, locked_by, locked_until, attempts, max_attempts, last_error, processed, success, created_at, processed_at, executed_at, dedupe_key FROM media_jobs WHERE id = ?", (job_id,))
        if not job:
            logger.warning(f"Job {job_id} disappeared after claim, skipped.")
            continue

        try:
            if job["action"] == "grant":
                apply_grant_job(db, job)
            elif job["action"] == "sync":
                apply_sync_job(db, job)
            elif job["action"] == "revoke":
                apply_revoke_job(db, job)
            else:
                raise ValueError(f"Unknown action '{job['action']}'")

            db.execute(
                """
                UPDATE media_jobs
                SET status = 'success',
                    processed = 1,
                    success = 1,
                    processed_at = datetime('now'),
                    executed_at = datetime('now'),
                    locked_by = NULL,
                    locked_until = NULL,
                    last_error = NULL
                WHERE id = ?
                """,
                (job_id,),
            )

            db.execute(
                "DELETE FROM media_jobs WHERE id = ? AND status = 'success' AND success = 1",
                (job_id,),
            )

            processed += 1
            logger.info(f"Job {job_id} OK -> deleted")

        except PendingPlexInvite as e:
            msg = str(e)
            run_after = (datetime.utcnow() + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")

            logger.info(f"Job {job_id} deferred pending invite until {run_after}: {msg}")

            db.execute(
                """
                UPDATE media_jobs
                SET status = 'queued',
                    processed = 0,
                    success = 0,
                    run_after = ?,
                    locked_by = NULL,
                    locked_until = NULL,
                    executed_at = datetime('now'),
                    last_error = ?
                WHERE id = ?
                """,
                (run_after, msg[:1000], job_id),
            )

        except Exception as e:
            errors += 1
            attempts = int(job["attempts"] or 0)
            max_attempts = int(job["max_attempts"] or 10)
            msg = str(e)

            logger.exception(f"Error while processing job {job_id}: {msg}")

            if attempts >= max_attempts:
                db.execute(
                    """
                    UPDATE media_jobs
                    SET status = 'error',
                        processed = 1,
                        success = 0,
                        processed_at = datetime('now'),
                        executed_at = datetime('now'),
                        locked_by = NULL,
                        locked_until = NULL,
                        last_error = ?
                    WHERE id = ?
                    """,
                    (msg[:1000], job_id),
                )
            else:
                delay_minutes = min(120, max(5, attempts * 10))
                run_after = (datetime.utcnow() + timedelta(minutes=delay_minutes)).strftime("%Y-%m-%d %H:%M:%S")

                db.execute(
                    """
                    UPDATE media_jobs
                    SET status = 'queued',
                        processed = 0,
                        success = 0,
                        run_after = ?,
                        locked_by = NULL,
                        locked_until = NULL,
                        executed_at = datetime('now'),
                        last_error = ?
                    WHERE id = ?
                    """,
                    (run_after, msg[:1000], job_id),
                )

    cleanup_old_jobs(db)
    logger.debug("=== APPLY PLEX ACCESS UPDATES : END ===")

    return {"processed": processed, "errors": errors}
