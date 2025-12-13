import time
from plexapi.server import PlexServer
from logging_utils import get_logger

logger = get_logger("apply_plex_access_updates")


def wait_for_task_idle(db, name):
    """Attend que la tâche <name> ne soit plus en cours."""
    while True:
        row = db.execute("SELECT status FROM tasks WHERE name = ?", (name,)).fetchone()
        if not row or row["status"] != "running":
            return
        logger.info(f"⏳ En attente que la tâche {name} termine…")
        time.sleep(2)


def disable_task(db, name):
    db.execute("UPDATE tasks SET enabled = 0 WHERE name = ?", (name,))
    db.commit()


def enable_task(db, name):
    db.execute("UPDATE tasks SET enabled = 1 WHERE name = ?", (name,))
    db.commit()


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

def cleanup_old_jobs(db):
    """
    Supprime les anciens jobs terminés ou en erreur.
    - Jobs processed = 1  (déjà traités)
    - Jobs en erreur = ceux avec processed = 0 et qui ont une action qui a échoué auparavant
      → dans notre cas, on considère tout job non traité et ancien comme "en erreur".
    """

    # 1. Supprimer tous les jobs traités
    deleted_processed = db.execute(
        "DELETE FROM plex_jobs WHERE processed = 1"
    ).rowcount

    # 2. Supprimer les jobs en erreur (processed = 0 mais anciens)
    # On supprime tous les jobs non traités PLUS ANCIENS qu'une minute
    deleted_failed = db.execute(
        """
        DELETE FROM plex_jobs
        WHERE processed = 0
        AND created_at < datetime('now', '-1 minute')
        """
    ).rowcount

    db.commit()

    logger.info(
        f"🧹 Nettoyage jobs : {deleted_processed} traités supprimés, "
        f"{deleted_failed} en erreur supprimés."
    )


def apply_grant_job(db, job):
    """
    Ajoute une bibliothèque à un utilisateur Plex
    en reproduisant EXACTEMENT la logique de plex_api_share.py (JBOPS),
    avec les flags allow* en 0/1 plutôt que True/False.
    """

    server_id = job["server_id"]
    lib_id    = job["library_id"]
    user_id   = job["user_id"]

    # --- RÉCUP DATA DB ----------------------------------------------------
    server = db.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
    library = db.execute("SELECT * FROM libraries WHERE id=?", (lib_id,)).fetchone()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    if not server or not library or not user:
        raise RuntimeError("Serveur / bibliothèque / user introuvable")

    logger.info(
        f"➡ Mise à jour accès : {user['username']} ← {library['name']} sur {server['name']}"
    )

    plex = get_plex(server)
    account = plex.myPlexAccount()

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

    # --- PERMISSIONS (0/1 plutôt que True/False) --------------------------
    perms = db.execute(
        """
        SELECT *
        FROM user_servers
        WHERE user_id=? AND server_id=?
        """,
        (user_id, server_id),
    ).fetchone()

    if perms:
        allowSync = 1 if perms["allow_sync"] else 0
        allowCameraUpload = 1 if perms["allow_camera_upload"] else 0
        allowChannels = 1 if perms["allow_channels"] else 0

        filterMovies = perms["filter_movies"]
        filterTelevision = perms["filter_television"]
        filterMusic = perms["filter_music"]
    else:
        # Valeurs par défaut si aucune ligne user_servers
        allowSync = 0
        allowCameraUpload = 0
        allowChannels = 0
        filterMovies = ""
        filterTelevision = ""
        filterMusic = ""

    # --- APPEL updateFriend() EXACT JBOPS ---------------------------------
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
    user_id   = job["user_id"]

    # Récup serveur + user
    server = db.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    if not server or not user:
        raise RuntimeError("Serveur ou utilisateur introuvable (sync)")

    logger.info(f"🔄 SYNC accès complet : {user['username']} sur {server['name']}")

    plex = get_plex(server)
    account = plex.myPlexAccount()

    # Récup MyPlexUser
    try:
        plex_user = account.user(user["username"])
    except Exception:
        logger.error(f"Impossible de récupérer MyPlexUser pour {user['username']}")
        raise

    # Récup ALL libraries autorisées pour cet user + serveur
    rows = db.execute(
        """
        SELECT l.name
        FROM shared_libraries sl
        JOIN libraries l ON sl.library_id = l.id
        WHERE sl.user_id = ? AND l.server_id = ?
        """,
        (user_id, server_id),
    ).fetchall()

    sections = [r["name"] for r in rows]

    logger.info(f"Bibliothèques appliquées au user ({len(sections)}): {sections}")

    # Récup permissions user_servers
    perms = db.execute(
        "SELECT * FROM user_servers WHERE user_id=? AND server_id=?",
        (user_id, server_id),
    ).fetchone()

    if perms:
        allowSync          = 1 if perms["allow_sync"] else 0
        allowCameraUpload  = 1 if perms["allow_camera_upload"] else 0
        allowChannels      = 1 if perms["allow_channels"] else 0
        filterMovies       = perms["filter_movies"]
        filterTelevision   = perms["filter_television"]
        filterMusic        = perms["filter_music"]
    else:
        allowSync = allowCameraUpload = allowChannels = 0
        filterMovies = filterTelevision = filterMusic = ""

    # Application
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
        logger.info("✔ SYNC appliqué avec succès")
    except Exception:
        logger.exception("❌ updateFriend() a échoué lors du sync")
        raise




def run(task_id, db):
    # delete old jobs
    cleanup_old_jobs(db)



    """Tâche principale appelée par tasks_engine."""
    logger.info("=== APPLY PLEX ACCESS UPDATES : DÉBUT ===")

    # Désactiver sync_plex
    disable_task(db, "sync_plex")
    logger.info("⛔ sync_plex désactivée temporairement")

    # Attendre que sync_plex ne soit plus running
    wait_for_task_idle(db, "sync_plex")

    # Récupération des jobs non traités
    jobs = db.execute(
        """
        SELECT *
        FROM plex_jobs
        WHERE processed = 0
        ORDER BY id ASC
        LIMIT 50
        """
    ).fetchall()

    if not jobs:
        logger.info("Aucun job à traiter.")
        enable_task(db, "sync_plex")
        return

    logger.info(f"{len(jobs)} job(s) à traiter…")

    # Traitement individuel
    for job in jobs:
        try:
            if job["action"] == "grant":
                apply_grant_job(db, job)

            elif job["action"] == "sync":
                apply_sync_job(db, job)


            # Suppression du job après traitement
            db.execute("DELETE FROM plex_jobs WHERE id = ?", (job["id"],))
            db.commit()

            logger.info(f"Job {job['id']} supprimé ✔")

        except Exception:
            # On loggue mais on ne supprime pas → permet retry manuel
            logger.exception(f"❌ Erreur dans le job {job['id']}")
            # On laisse processed=0 pour pouvoir inspecter ensuite
            continue

    # Réactiver sync_plex
    enable_task(db, "sync_plex")
    logger.info("✅ sync_plex réactivée")

    # Désactivation de la tâche
    disable_task(db, "apply_plex_access_updates")
    logger.info("🔕 Tâche apply_plex_access_updates désactivée")

    logger.info("=== APPLY PLEX ACCESS UPDATES : FIN ===")
