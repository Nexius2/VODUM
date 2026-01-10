import time
import json
from plexapi.server import PlexServer
from logging_utils import get_logger

logger = get_logger("apply_plex_access_updates")

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
    """
    Wrap requests.Session.request utilisé par plexapi, pour logger EXACTEMENT
    ce qui est envoyé (method/url/params/data/json) + code retour.
    Les logs passent dans logging_utils (donc fichier app.log).
    """
    if not session or not hasattr(session, "request"):
        logger.warning(f"[{label}] session invalide, impossible d'installer le logger HTTP")
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
            logger.exception(f"[{label}] impossible de logger la réponse HTTP")

        return resp

    session.request = wrapped_request
    session._vodum_http_logger_installed = True
    logger.warning(f"[{label}] logger HTTP installé ✅")

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
        logger.info(f"⏳ En attente que la tâche {name} termine…")
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
    """Connexion PlexAPI sécurisée."""
    baseurl = (
        server_row["url"]
        or server_row["local_url"]
        or server_row["public_url"]
    )
    token = server_row["token"]

    if not baseurl or not token:
        raise RuntimeError(f"Serveur incomplet (URL/token) : {server_row['name']}")

    return PlexServer(baseurl, token)

def get_all_plex_section_titles(plex):
    """
    JBOPS: sections_lst = [x.title for x in plex.library.sections()]
    On récupère les TITRES réels côté Plex (le plus fiable).
    """
    try:
        return [s.title for s in plex.library.sections()]
    except Exception:
        logger.exception("❌ Impossible de lire plex.library.sections()")
        raise


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
          AND success = 1
          AND executed_at IS NOT NULL
          AND executed_at < datetime('now', '-7 days')
        """
    ).rowcount

    logger.info(f"🧹 Nettoyage jobs : {deleted} job(s) Plex success supprimé(s) (>7 jours).")


def resolve_media_user(db, vodum_user_id: int, server_id: int):
    """
    Convertit un user canonique (vodum_user_id) en user 'media_users' lié au serveur.
    C'est indispensable depuis le passage à media_jobs.
    """
    if vodum_user_id is None:
        raise RuntimeError("Job invalide: vodum_user_id est NULL")

    user = db.query_one(
        """
        SELECT *
        FROM media_users
        WHERE vodum_user_id = ?
          AND server_id = ?
        """,
        (vodum_user_id, server_id),
    )

    if not user:
        raise RuntimeError(
            f"Aucun media_user trouvé pour vodum_user_id={vodum_user_id} sur server_id={server_id}"
        )

    return user

def is_owner_media_user(user_row) -> bool:
    try:
        return (user_row["role"] or "").strip().lower() == "owner"
    except Exception:
        return False


def _get_plex_share_settings_from_user(user_row):
    """
    Récupère les paramètres de partage Plex depuis media_users.details_json.

    On s'aligne sur un schéma classique:
      details_json = {
        "plex_share": {
          "allowSync": true/false,
          "allowCameraUpload": true/false,
          "allowChannels": true/false,
          "filterMovies": "...",
          "filterTelevision": "...",
          "filterMusic": "..."
        }
      }

    Si absent ou invalide => valeurs par défaut.
    """
    allowSync = 0
    allowCameraUpload = 0
    allowChannels = 0
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

    allowSync = 1 if plex_share.get("allowSync") else 0
    allowCameraUpload = 1 if plex_share.get("allowCameraUpload") else 0
    allowChannels = 1 if plex_share.get("allowChannels") else 0

    filterMovies = plex_share.get("filterMovies") or ""
    filterTelevision = plex_share.get("filterTelevision") or ""
    filterMusic = plex_share.get("filterMusic") or ""

    return allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic


def apply_grant_job(db, job):
    """
    Ajoute une bibliothèque à un utilisateur Plex
    en reproduisant EXACTEMENT la logique de plex_api_share.py (JBOPS),
    avec les flags allow* en 0/1 plutôt que True/False.
    """

    server_id = job["server_id"]
    lib_id = job["library_id"]
    vodum_user_id = job["vodum_user_id"]

    # Résolution user canonique -> media_users (lié au serveur)
    user = resolve_media_user(db, vodum_user_id, server_id)
    user_id = user["id"]
    if is_owner_media_user(user):
        logger.info(
            f"⏭️ Skip GRANT (owner) : username={user['username']} "
            f"server_id={server_id} library_id={lib_id}"
        )
        return



    # --- RÉCUP DATA DB ----------------------------------------------------
    server = db.query_one(
        "SELECT * FROM servers WHERE id=?",
        (server_id,)
    )

    library = db.query_one(
        "SELECT * FROM libraries WHERE id=?",
        (lib_id,)
    )

#    user = db.query_one(
#        "SELECT * FROM media_users WHERE id=?",
#        (user_id,)
#    )

    if not server or not library or not user:
        raise RuntimeError("Serveur / bibliothèque / user introuvable")

    logger.info(
        f"➡ Mise à jour accès : {user['username']} ← {library['name']} sur {server['name']}"
    )

    plex = get_plex(server)
    account = plex.myPlexAccount()
    install_plex_http_logger(getattr(account, "_session", None), "PLEX_ACCOUNT")


    # --- RÉCUP OBJET MyPlexUser ------------------------------------------
    try:
        plex_user = account.user(user["username"])
    except Exception:
        logger.error(f"Impossible de récupérer MyPlexUser pour {user['username']}")
        raise

    # --- RÉCUP PARTAGES EXISTANTS (JBOPS) ---------------------------------
    current_sections = set()

    try:
        for srv in plex_user.servers:
            # JBOPS MATCH PAR NOM DU SERVEUR !!!
            if srv.name == plex.friendlyName:
                for section in srv.sections():
                    if getattr(section, "shared", False):
                        current_sections.add(section.title)
    except Exception:
        logger.exception("Erreur lecture des sections existantes")
        raise

    # --- AJOUTER LA NOUVELLE BIBLIOTHÈQUE (NOM!) --------------------------
    current_sections.add(library["name"])

    logger.info(f"Sections finales envoyées : {current_sections}")

    # --- PERMISSIONS (depuis media_users.details_json) --------------------
    allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic = (
        _get_plex_share_settings_from_user(user)
    )

    # --- APPEL updateFriend() EXACT JBOPS ---------------------------------
    
    log_updatefriend_payload(
        action="sync",
        server_row=server,
        user_row=user,
        plex_obj=plex,
        plex_user_obj=plex_user,
        sections=list(current_sections),
        allowSync=allowSync,
        allowCameraUpload=allowCameraUpload,
        allowChannels=allowChannels,
        filterMovies=filterMovies,
        filterTelevision=filterTelevision,
        filterMusic=filterMusic,
    )

    
    try:
        account.updateFriend(
            user=plex_user,
            server=plex,
            sections=list(current_sections),  # liste de noms
            allowSync=allowSync,
            allowCameraUpload=allowCameraUpload,
            allowChannels=allowChannels,
            filterMovies=filterMovies,
            filterTelevision=filterTelevision,
            filterMusic=filterMusic,
        )

        logger.info("✔ Accès modifié avec succès (méthode JBOPS)")

    except Exception:
        logger.exception("❌ updateFriend() a échoué")
        raise


def apply_sync_job(db, job):
    """
    Synchronise TOUTES les bibliothèques autorisées pour un user donné
    sur un serveur donné.
    Ce job est utilisé lorsque l'utilisateur clique sur "Save".
    """

    server_id = job["server_id"]
    vodum_user_id = job["vodum_user_id"]

    # Résolution user canonique -> media_users (lié au serveur)
    user = resolve_media_user(db, vodum_user_id, server_id)
    user_id = user["id"]
    if is_owner_media_user(user):
        logger.info(
            f"⏭️ Skip SYNC (owner) : username={user['username']} server_id={server_id}"
        )
        return


    # Récup serveur + user
    server = db.query_one(
        "SELECT * FROM servers WHERE id=?",
        (server_id,)
    )

    user = db.query_one(
        "SELECT * FROM media_users WHERE id=?",
        (user_id,)
    )

    if not server or not user:
        raise RuntimeError("Serveur ou utilisateur introuvable (sync)")

    logger.info(f"🔄 SYNC accès complet : {user['username']} sur {server['name']} (server_id={server_id}, user_id={user_id})")

    # Connexion Plex
    plex = get_plex(server)
    account = plex.myPlexAccount()
    install_plex_http_logger(getattr(account, "_session", None), "PLEX_ACCOUNT")


    # Debug serveur ciblé (DB vs Plex)
    try:
        baseurl = getattr(plex, "_baseurl", None) or getattr(plex, "baseurl", None)
        logger.info(
            f"🧪 Plex debug server: db_name='{server['name']}' "
            f"friendlyName='{plex.friendlyName}' baseurl='{baseurl}'"
        )
    except Exception:
        logger.exception("⚠️ Impossible de logger les infos serveur Plex (debug)")

    # Récup MyPlexUser
    try:
        plex_user = account.user(user["username"])
        logger.info(
            "🧪 Plex debug user: "
            f"db_username='{user['username']}' "
            f"plex_username='{getattr(plex_user, 'username', None)}' "
            f"plex_title='{getattr(plex_user, 'title', None)}' "
            f"plex_email='{getattr(plex_user, 'email', None)}' "
            f"plex_id='{getattr(plex_user, 'id', None)}'"
        )
    except Exception:
        logger.exception(f"❌ Impossible de récupérer MyPlexUser pour {user['username']}")
        raise

    # Récup ALL libraries autorisées pour cet user + serveur
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

    sections = [r["name"] for r in rows]
    if not sections:
        raise RuntimeError(
            f"Aucune bibliothèque trouvée en DB pour media_user_id={user_id} "
            f"(vodum_user_id={vodum_user_id}) server_id={server_id}. "
            "Sync bloqué pour éviter de retirer tous les accès."
        )
    logger.info(f"📚 Sections DB (expected) ({len(sections)}): {sections}")

    # --- PERMISSIONS (depuis media_users.details_json) --------------------
    try:
        allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic = (
            _get_plex_share_settings_from_user(user)
        )
    except Exception:
        logger.exception("❌ Impossible de lire les paramètres plex_share depuis details_json")
        raise

    logger.info(
        "🧾 Plex share settings: "
        f"allowSync={allowSync} allowCameraUpload={allowCameraUpload} allowChannels={allowChannels} "
        f"filterMovies='{filterMovies}' filterTelevision='{filterTelevision}' filterMusic='{filterMusic}'"
    )

    # Application
    logger.warning(
        f"🚫 APPLY SYNC intent: user='{user['username']}' "
        f"server_friendly='{plex.friendlyName}' sections={sections}"
    )

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


    try:
        account.updateFriend(
            user=plex_user,
            server=plex,
            sections=sections,  # liste de noms !
            allowSync=allowSync,
            allowCameraUpload=allowCameraUpload,
            allowChannels=allowChannels,
            filterMovies=filterMovies,
            filterTelevision=filterTelevision,
            filterMusic=filterMusic,
        )
        logger.info("✔ SYNC appliqué avec succès (updateFriend OK)")

    except Exception:
        logger.exception("❌ updateFriend() a échoué lors du sync")
        raise

    # --- POST-CHECK : relire ce que Plex croit vraiment après updateFriend ---
    try:
        refreshed = account.user(user["username"])
        shared_on_server = None
        server_names = []

        for srv in getattr(refreshed, "servers", []) or []:
            srv_name = getattr(srv, "name", None)
            if srv_name:
                server_names.append(srv_name)

            if srv_name == plex.friendlyName:
                # sections() -> liste des sections côté "partage" pour ce user sur CE serveur
                shared_on_server = [
                    s.title for s in srv.sections()
                    if getattr(s, "shared", False)
                ]
                break

        logger.warning(
            f"🧾 POST-CHECK share state: user='{user['username']}' "
            f"server_friendly='{plex.friendlyName}' matched_server_sections={shared_on_server} "
            f"user_servers={server_names}"
        )

    except Exception:
        logger.exception("⚠️ POST-CHECK failed: impossible de relire l’état de partage après updateFriend()")

def apply_revoke_job(db, job):
    """
    Retire TOUS les accès aux bibliothèques pour un utilisateur sur un serveur.
    On conserve la méthode JBOPS (updateFriend avec sections=[]).
    """
    server_id = job["server_id"]
    vodum_user_id = job["vodum_user_id"]

    user = resolve_media_user(db, vodum_user_id, server_id)
    if is_owner_media_user(user):
        logger.info(
            f"⏭️ Skip REVOKE (owner) : username={user['username']} server_id={server_id}"
        )
        return


    server = db.query_one(
        "SELECT * FROM servers WHERE id=?",
        (server_id,)
    )
    if not server:
        raise RuntimeError(f"Serveur introuvable (id={server_id})")

    plex = get_plex(server)


    try:
        account = plex.myPlexAccount()
        # DEBUG: log HTTP réel + payload exact
        install_plex_http_logger(getattr(account, "_session", None), "PLEX_ACCOUNT")
        plex_user = account.user(user["username"])
    except Exception:
        logger.exception(f"❌ Impossible de récupérer MyPlexUser pour {user['username']}")
        raise

    allowSync, allowCameraUpload, allowChannels, filterMovies, filterTelevision, filterMusic = (
        _get_plex_share_settings_from_user(user)
    )

    logger.warning(
        f"🚫 APPLY REVOKE intent: user='{user['username']}' "
        f"server_friendly='{plex.friendlyName}' sections=[] (revoke all)"
    )

    log_updatefriend_payload(
        action="revoke",
        server_row=server,
        user_row=user,
        plex_obj=plex,
        plex_user_obj=plex_user,
        sections=[],
        allowSync=allowSync,
        allowCameraUpload=allowCameraUpload,
        allowChannels=allowChannels,
        filterMovies=filterMovies,
        filterTelevision=filterTelevision,
        filterMusic=filterMusic,
    )


    # EXACTEMENT comme JBOPS: on unshare en envoyant les TITRES des sections + removeSections=True
    sections_titles = get_all_plex_section_titles(plex)

    # Log clair : ce qu'on envoie "façon JBOPS"
    logger.warning(
        "### JBOPS UNHARE CALL ###\n"
        f"username={user['username']}\n"
        f"server_id={server_id}\n"
        f"server_name={server['name'] if server else None}\n"
        f"plex_friendlyName={getattr(plex, 'friendlyName', None)}\n"
        f"sections_titles={sections_titles}\n"
        f"allowSync={allowSync}\n"
        f"allowCameraUpload={allowCameraUpload}\n"
        f"allowChannels={allowChannels}\n"
        f"filterMovies={filterMovies}\n"
        f"filterTelevision={filterTelevision}\n"
        f"filterMusic={filterMusic}\n"
        "########################"
    )

    try:
        account.updateFriend(
            user=user["username"],     # ✅ comme JBOPS: STRING (user)
            server=plex,               # ✅ plex server object
            removeSections=True,       # ✅ JBOPS
            sections=sections_titles,  # ✅ JBOPS: liste de TITRES
            allowSync=allowSync,
            allowCameraUpload=allowCameraUpload,
            allowChannels=allowChannels,
            filterMovies=filterMovies,
            filterTelevision=filterTelevision,
            filterMusic=filterMusic,
        )
        logger.info("✔ REVOKE appliqué avec succès (méthode JBOPS : removeSections=True + sections_titles)")
    except Exception:
        logger.exception("❌ updateFriend() a échoué lors du revoke (méthode JBOPS)")
        raise



def run(task_id: int, db):
    logger.info("=== APPLY PLEX ACCESS UPDATES : DÉBUT ===")

    jobs = db.query(
        """
        SELECT *
        FROM media_jobs
        WHERE provider = 'plex'
          AND processed = 0
        ORDER BY id ASC
        LIMIT 50
        """
    )

    if not jobs:
        logger.info("Aucun job à traiter.")
        return

    logger.info(f"{len(jobs)} job(s) à traiter...")

    for job in jobs:
        job_id = job["id"]

        try:
            # 1) Marquer le job comme "pris en charge"
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

            # 2) Exécuter l'action
            if job["action"] == "grant":
                apply_grant_job(db, job)
            elif job["action"] == "sync":
                apply_sync_job(db, job)
            elif job["action"] == "revoke":
                apply_revoke_job(db, job)
            else:
                raise ValueError(f"Action inconnue '{job['action']}'")


            # 3) Succès
            db.execute(
                """
                UPDATE media_jobs
                SET success = 1,
                    executed_at = datetime('now')
                WHERE id = ?
                """,
                (job_id,)
            )

            # 4) Suppression uniquement si succès
            db.execute(
                "DELETE FROM media_jobs WHERE id = ? AND success = 1",
                (job_id,)
            )

            logger.info(f"Job {job_id} OK ✔ (success=1) -> supprimé")

        except Exception as e:
            logger.exception(f"❌ Erreur dans le job {job_id}: {e}")

            # Job conservé pour debug/retry + remis en pending
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
    logger.info("=== APPLY PLEX ACCESS UPDATES : FIN ===")

