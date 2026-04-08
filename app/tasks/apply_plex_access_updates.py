import time
import json
from plexapi.server import PlexServer
from logging_utils import get_logger
import xml.etree.ElementTree as ET
from plexapi.exceptions import BadRequest
from core.providers.plex_users import plex_invite_and_share
import re
import requests
from core.plex_rate_limit import install_plex_rate_limit

logger = get_logger("apply_plex_access_updates")

class PendingPlexInvite(RuntimeError):
    """
    User invité sur Plex mais pas encore accepté.
    Ce n'est pas une erreur dure : le job doit être reporté.
    """
    pass

def _redact_headers(headers: dict):
    """Masque les infos sensibles avant log."""
    if not headers:
        return headers
    h = dict(headers)
    for k in list(h.keys()):
        lk = k.lower()
        if lk in ("x-plex-token", "authorization"):
            h[k] = "***REDACTED***"
    return h


def install_plex_http_logger(session, label: str):
    if not session or not hasattr(session, "request"):
        logger.warning(f"[{label}] invalid session, unable to install HTTP logger")
        return

    if getattr(session, "_vodum_http_logger_installed", False):
        return

    original_request = session.request

    def wrapped_request(method, url, **kwargs):
        headers = _redact_headers(kwargs.get("headers") or {})
        params = kwargs.get("params")
        data = kwargs.get("data")
        js = kwargs.get("json")

        logger.warning(
            f"[{label}] >>> REQUEST {method} {url}\n"
            f"[{label}] headers={headers}\n"
            f"[{label}] params={params}\n"
            f"[{label}] data={data}\n"
            f"[{label}] json={js}"
        )

        resp = original_request(method, url, **kwargs)

        try:
            txt = resp.text if hasattr(resp, "text") else None
            logger.warning(
                f"[{label}] <<< RESPONSE status={getattr(resp, 'status_code', None)} "
                f"len={len(txt) if txt else 0} "
                f"text_preview={(txt[:800] if txt else None)}"
            )
        except Exception:
            logger.exception(f"[{label}] failed to log HTTP response")

        return resp

    session.request = wrapped_request
    session._vodum_http_logger_installed = True
    logger.warning(f"[{label}] HTTP logger installed")


def row_get(row, key, default=None):
    """
    Supporte sqlite3.Row / dict / objet.
    sqlite3.Row ne supporte pas .get(), mais supporte row['col'].
    """
    if row is None:
        return default

    # dict-like ?
    try:
        if hasattr(row, "keys") and key in row.keys():
            return row[key]
    except Exception:
        pass

    # objet ?
    try:
        return getattr(row, key)
    except Exception:
        return default

def _details_json_as_dict(user_row):
    raw = row_get(user_row, "details_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def is_pending_invite_media_user(user_row) -> bool:
    accepted_at = str(row_get(user_row, "accepted_at") or "").strip()
    if accepted_at:
        return False

    details = _details_json_as_dict(user_row)
    invite_state = details.get("plex_invite_state") or {}
    if isinstance(invite_state, dict) and bool(invite_state.get("is_pending")):
        return True

    ext_id = str(row_get(user_row, "external_user_id") or "").strip()
    email = str(row_get(user_row, "email") or "").strip()
    username = str(row_get(user_row, "username") or "").strip()

    return (not accepted_at) and (not ext_id) and bool(email or username)

def resolve_plex_user(account, media_user_row):
    """
    Résout un MyPlexUser de façon robuste.
    Ordre réel :
    1. external_user_id (colonne DB + details_json.plex_user.id)
    2. email (colonne DB + details_json)
    3. username (colonne DB + details_json)
    4. title
    5. fallback account.user(...)
    """
    details = _details_json_as_dict(media_user_row)
    plex_user_details = details.get("plex_user") or {}
    plex_share_details = details.get("plex_share") or {}

    def norm(v):
        return str(v or "").strip()

    def norm_lower(v):
        return norm(v).lower()

    db_ext_id = norm(row_get(media_user_row, "external_user_id"))
    db_email = norm_lower(row_get(media_user_row, "email"))
    db_username = norm(row_get(media_user_row, "username"))

    candidate_ids = []
    candidate_emails = []
    candidate_usernames = []

    for v in [
        db_ext_id,
        plex_user_details.get("id"),
    ]:
        v = norm(v)
        if v and v not in candidate_ids:
            candidate_ids.append(v)

    for v in [
        db_email,
        plex_user_details.get("email"),
        plex_share_details.get("email"),
    ]:
        v = norm_lower(v)
        if v and v not in candidate_emails:
            candidate_emails.append(v)

    for v in [
        db_username,
        plex_user_details.get("username"),
        plex_share_details.get("username"),
    ]:
        v = norm(v)
        if v and v not in candidate_usernames:
            candidate_usernames.append(v)

    try:
        plex_users = list(account.users())
    except Exception:
        logger.exception("Unable to list Plex users via account.users()")
        plex_users = []

    # 1) Match par id
    for wanted_id in candidate_ids:
        for pu in plex_users:
            if norm(getattr(pu, "id", None)) == wanted_id:
                return pu

    # 2) Match par email
    for wanted_email in candidate_emails:
        for pu in plex_users:
            if norm_lower(getattr(pu, "email", None)) == wanted_email:
                return pu

    # 3) Match par username
    for wanted_username in candidate_usernames:
        for pu in plex_users:
            if norm(getattr(pu, "username", None)) == wanted_username:
                return pu

    # 4) Match par title
    for wanted_username in candidate_usernames:
        for pu in plex_users:
            if norm(getattr(pu, "title", None)) == wanted_username:
                return pu

    # 5) fallback ancien comportement, mais sur toutes les valeurs possibles
    for wanted_username in candidate_usernames:
        try:
            return account.user(wanted_username)
        except Exception:
            pass

    for wanted_email in candidate_emails:
        try:
            return account.user(wanted_email)
        except Exception:
            pass

    if is_pending_invite_media_user(media_user_row):
        raise PendingPlexInvite(
            f"Plex invite still pending acceptance for username={db_username!r}, email={db_email!r}"
        )

    available = [
        {
            "id": norm(getattr(pu, "id", None)),
            "username": norm(getattr(pu, "username", None)),
            "title": norm(getattr(pu, "title", None)),
            "email": norm(getattr(pu, "email", None)),
        }
        for pu in plex_users
    ]

    raise RuntimeError(
        "Unable to resolve Plex user from media_users row "
        f"(external_user_id={db_ext_id!r}, username={db_username!r}, email={db_email!r}). "
        f"details_json.plex_user={plex_user_details!r}. "
        f"details_json.plex_share={plex_share_details!r}. "
        f"Available Plex users sample={available[:10]}"
    )


def sync_media_user_identity_from_plex(db, media_user_row, plex_user_obj):
    """
    Auto-corrige media_users quand Plex renvoie enfin une identité réelle.
    Important :
    - met à jour username / email
    - met à jour external_user_id
    - marque accepted_at si absent
    - remet plex_invite_state en friend/non-pending
    """
    media_user_id = row_get(media_user_row, "id")
    if not media_user_id:
        return

    new_username = str(
        getattr(plex_user_obj, "username", None)
        or getattr(plex_user_obj, "title", None)
        or ""
    ).strip()

    new_email = str(getattr(plex_user_obj, "email", None) or "").strip()
    new_external_user_id = str(getattr(plex_user_obj, "id", None) or "").strip()

    old_username = str(row_get(media_user_row, "username") or "").strip()
    old_email = str(row_get(media_user_row, "email") or "").strip()
    old_external_user_id = str(row_get(media_user_row, "external_user_id") or "").strip()
    old_accepted_at = str(row_get(media_user_row, "accepted_at") or "").strip()

    details = _details_json_as_dict(media_user_row)
    details["plex_invite_state"] = {
        "is_friend": True,
        "is_pending": False,
        "primary_server_id": row_get(media_user_row, "server_id"),
    }

    details["plex_user"] = {
        **(details.get("plex_user") or {}),
        "id": new_external_user_id or old_external_user_id or None,
        "username": new_username or old_username or None,
        "email": new_email or old_email or None,
        "avatar": getattr(plex_user_obj, "thumb", None),
        "accepted_at": old_accepted_at or "synced",
    }

    changed = (
        (new_username and new_username != old_username)
        or (new_email and new_email != old_email)
        or (new_external_user_id and new_external_user_id != old_external_user_id)
        or (not old_accepted_at)
    )

    db.execute(
        """
        UPDATE media_users
        SET username = ?,
            email = ?,
            external_user_id = ?,
            accepted_at = CASE
                WHEN accepted_at IS NULL OR TRIM(accepted_at) = '' THEN datetime('now')
                ELSE accepted_at
            END,
            details_json = ?
        WHERE id = ?
        """,
        (
            new_username or old_username,
            new_email or old_email,
            new_external_user_id or old_external_user_id or None,
            json.dumps(details),
            media_user_id,
        ),
    )

    if changed:
        logger.info(
            f"[PLEX USER SYNC] media_user_id={media_user_id} "
            f"username: {old_username!r} -> {new_username!r}, "
            f"email: {old_email!r} -> {new_email!r}, "
            f"external_user_id: {old_external_user_id!r} -> {new_external_user_id!r}, "
            f"accepted_at was empty={not bool(old_accepted_at)}"
        )

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
            "SELECT * FROM media_users WHERE id = ?",
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

def log_updatefriend_payload(action: str, server_row, user_row, plex_obj, plex_user_obj,
                            sections, allowSync, allowCameraUpload, allowChannels,
                            filterMovies, filterTelevision, filterMusic):
    """
    Log "fonctionnel" (avant l'appel) pour être sûr que les bonnes variables sont envoyées.
    Compatible sqlite3.Row / dict.
    """
    logger.warning(
        "### PLEX updateFriend() PAYLOAD ###\n"
        f"action={action}\n"
        f"db_server_id={row_get(server_row, 'id')}\n"
        f"db_server_name={row_get(server_row, 'name')}\n"
        f"db_server_url={row_get(server_row, 'url')}\n"
        f"db_server_local_url={row_get(server_row, 'local_url')}\n"
        f"db_server_public_url={row_get(server_row, 'public_url')}\n"
        f"plex_friendlyName={getattr(plex_obj, 'friendlyName', None)}\n"
        f"db_username={row_get(user_row, 'username')}\n"
        f"plex_username={getattr(plex_user_obj, 'username', None)}\n"
        f"sections={sections}\n"
        f"allowSync={allowSync} ({type(allowSync).__name__})\n"
        f"allowCameraUpload={allowCameraUpload} ({type(allowCameraUpload).__name__})\n"
        f"allowChannels={allowChannels} ({type(allowChannels).__name__})\n"
        f"filterMovies={filterMovies}\n"
        f"filterTelevision={filterTelevision}\n"
        f"filterMusic={filterMusic}\n"
        "################################"
    )


def wait_for_task_idle(db, name):
    """Attend que la tâche <name> ne soit plus en cours."""
    while True:
        row = db.query_one(
            "SELECT status FROM tasks WHERE name = ?",
            (name,)
        )

        if not row or row["status"] != "running":
            return
        logger.info(f"⏳ Waiting for task {name} to finish…")
        time.sleep(2)


def disable_task(db, name):
    db.execute(
        "UPDATE tasks SET enabled = 0 WHERE name = ?",
        (name,)
    )


def enable_task(db, name):
    db.execute(
        "UPDATE tasks SET enabled = 1 WHERE name = ?",
        (name,)
    )


def get_plex(server_row):
    """Connexion PlexAPI sécurisée avec rate limit 1 req/sec/server."""
    baseurl = (
        server_row["url"]
        or server_row["local_url"]
        or server_row["public_url"]
    )
    token = server_row["token"]

    if not baseurl or not token:
        raise RuntimeError(f"Incomplete server configuration (URL/token) : {server_row['name']}")

    session = requests.Session()
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
    Returns list of dicts: {id, username, email, userID}
    """
    url = f"https://plex.tv/api/servers/{machine_id}/shared_servers"
    resp = account.query(url, account._session.get)

    # plexapi peut renvoyer un Element directement
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
        out.append(
            {
                "id": ss.attrib.get("id"),
                "username": ss.attrib.get("username"),
                "email": ss.attrib.get("email"),
                "userID": ss.attrib.get("userID") or ss.attrib.get("userId"),
                "invitedId": ss.attrib.get("invitedId") or ss.attrib.get("invitedID") or ss.attrib.get("invited_id"),
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


def cleanup_old_jobs(db):
    """
    Nettoyage SAFE :
    - Ne supprime jamais les jobs en attente (processed=0) ni les jobs en échec.
    - Supprime uniquement les jobs success=1 vieux (ex: 7 jours).
    """
    deleted = db.execute(
        """
        DELETE FROM media_jobs
        WHERE provider = 'plex'
          AND action IN ('grant','revoke','sync')
          AND success = 1
          AND executed_at IS NOT NULL
          AND executed_at < datetime('now', '-7 days')
        """
    ).rowcount

    logger.info(f"Jobs cleanup: {deleted} successful Plex job(s) deleted")

def _job_payload_as_dict(job):
    raw = row_get(job, "payload_json")
    if not raw:
        return {}

    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}

def resolve_media_user(db, vodum_user_id: int, server_id: int, job=None):
    """
    Résout le media_user à utiliser pour un job Plex.

    Priorité :
    1. preferred_media_user_id / media_user_id transmis dans payload_json
    2. fallback sur la meilleure ligne trouvée pour (vodum_user_id, server_id)
    """
    payload = _job_payload_as_dict(job)
    preferred_media_user_id = (
        payload.get("preferred_media_user_id")
        or payload.get("media_user_id")
    )

    if preferred_media_user_id is not None:
        try:
            preferred_media_user_id = int(preferred_media_user_id)
        except Exception:
            preferred_media_user_id = None

    if preferred_media_user_id:
        row = db.query_one(
            """
            SELECT *
            FROM media_users
            WHERE id = ?
              AND server_id = ?
            """,
            (preferred_media_user_id, server_id),
        )
        if row:
            return row

    if vodum_user_id is None:
        raise RuntimeError("Invalid job: vodum_user_id is NULL")

    rows = db.query(
        """
        SELECT *
        FROM media_users
        WHERE vodum_user_id = ?
          AND server_id = ?
        ORDER BY
            CASE WHEN LOWER(COALESCE(role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(type, '')) = 'unfriend' THEN 1 ELSE 0 END ASC,
            id ASC
        """,
        (vodum_user_id, server_id),
    )

    if not rows:
        raise RuntimeError(
            f"No media_user found for vodum_user_id={vodum_user_id} on server_id={server_id}"
        )

    if len(rows) > 1:
        logger.warning(
            f"[MEDIA USER DUPLICATE] vodum_user_id={vodum_user_id} server_id={server_id} "
            f"rows={[row_get(r, 'id') for r in rows]}"
        )

    return rows[0]


def is_owner_media_user(user_row) -> bool:
    try:
        return (user_row["role"] or "").strip().lower() == "owner"
    except Exception:
        return False


def _parse_bool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    return default


def _get_plex_share_settings_from_user(user_row):
    """
    Récupère les paramètres de partage Plex depuis media_users.details_json.
    Retourne des BOOL.
    """
    allowSync = False
    allowCameraUpload = False
    allowChannels = False
    filterMovies = ""
    filterTelevision = ""
    filterMusic = ""

    if not user_row:
        return allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic

    try:
        raw = user_row["details_json"]
    except Exception:
        raw = None

    if not raw:
        return allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic

    try:
        details = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        details = {}

    plex_share = details.get("plex_share", {})
    if not isinstance(plex_share, dict):
        plex_share = {}

    allowSync = _parse_bool(plex_share.get("allowSync"), default=False)
    allowCameraUpload = _parse_bool(plex_share.get("allowCameraUpload"), default=False)
    allowChannels = _parse_bool(plex_share.get("allowChannels"), default=False)

    filterMovies = str(plex_share.get("filterMovies") or "")
    filterTelevision = str(plex_share.get("filterTelevision") or "")
    filterMusic = str(plex_share.get("filterMusic") or "")

    logger.info(
        f"[SETTINGS] allowSync={allowSync} ({type(allowSync).__name__}) "
        f"allowCameraUpload={allowCameraUpload} ({type(allowCameraUpload).__name__}) "
        f"allowChannels={allowChannels} ({type(allowChannels).__name__})"
    )

    return allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic


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

    server = db.query_one("SELECT * FROM servers WHERE id=?", (server_id,))
    library = db.query_one("SELECT * FROM libraries WHERE id=?", (lib_id,))

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

    shared_server_id = _ensure_shared_server(account, machine_id, plex_user, section_ids)

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

    server = db.query_one("SELECT * FROM servers WHERE id=?", (server_id,))
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
        logger.warning("SYNC computed an empty section_ids list. Falling back to revoke.")
        apply_revoke_job(db, job)
        return

    shared_server_id = _ensure_shared_server(account, machine_id, plex_user, section_ids)

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

    server = db.query_one("SELECT * FROM servers WHERE id=?", (server_id,))
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

    url = f"https://plex.tv/api/servers/{machine_id}/shared_servers/{shared_server_id}"
    account.query(url, account._session.delete)
    logger.info("✅ REVOKE applied via plex.tv legacy shared_servers API")


def run(task_id: int, db):
    logger.info("=== APPLY PLEX ACCESS UPDATES : START ===")

    jobs = db.query(
        """
        SELECT *
        FROM media_jobs
        WHERE provider = 'plex'
          AND processed = 0
          AND action IN ('grant','revoke','sync')
        ORDER BY id ASC
        LIMIT 50
        """
    )

    if not jobs:
        logger.info("No jobs to process.")
        return

    logger.info(f"{len(jobs)} job(s) to process...")

    for job in jobs:
        job_id = job["id"]

        try:
            db.execute(
                """
                UPDATE media_jobs
                SET processed = 1,
                    processed_at = COALESCE(processed_at, datetime('now')),
                    last_error = NULL
                WHERE id = ?
                """,
                (job_id,)
            )

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
                SET success = 1,
                    executed_at = datetime('now')
                WHERE id = ?
                """,
                (job_id,)
            )

            db.execute(
                "DELETE FROM media_jobs WHERE id = ? AND success = 1",
                (job_id,)
            )

            logger.info(f"Job {job_id} OK (success=1) -> deleted")

        except PendingPlexInvite as e:
            msg = str(e)
            logger.info(f"Job {job_id} deferred (pending invite): {msg}")

            db.execute(
                """
                UPDATE media_jobs
                SET success = 0,
                    processed = 0,
                    executed_at = datetime('now'),
                    last_error = ?
                WHERE id = ?
                """,
                (msg[:1000], job_id)
            )

        except Exception as e:
            logger.exception(f"Error while processing job {job_id}: {e}")

            db.execute(
                """
                UPDATE media_jobs
                SET success = 0,
                    processed = 0,
                    executed_at = datetime('now'),
                    attempts = COALESCE(attempts, 0) + 1,
                    last_error = ?
                WHERE id = ?
                """,
                (str(e)[:1000], job_id)
            )

    cleanup_old_jobs(db)
    logger.info("=== APPLY PLEX ACCESS UPDATES : END ===")