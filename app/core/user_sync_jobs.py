"""Provider-neutral orchestration of user access synchronization jobs."""

from core.media_jobs import insert_jellyfin_media_job, insert_plex_media_job
from logging_utils import get_logger


task_logger = get_logger("tasks_ui")


def get_preferred_plex_media_user_id(db, user_id: int, server_id: int):
    row = db.query_one(
        """
        SELECT id
        FROM media_users
        WHERE vodum_user_id = ?
          AND server_id = ?
          AND type = 'plex'
        ORDER BY
            CASE WHEN LOWER(COALESCE(role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(role, '')) = 'unfriended' THEN 1 ELSE 0 END ASC,
            id ASC
        LIMIT 1
        """,
        (user_id, server_id),
    )
    return int(row["id"]) if row and row["id"] is not None else None

def queue_plex_share_settings_sync(db, user_id: int, server_id: int, reason: str, *, wake_task=None):
    preferred_media_user_id = get_preferred_plex_media_user_id(
        db,
        user_id,
        server_id,
    )

    dedupe_key = f"plex:sync:server={server_id}:user={user_id}:share_settings"

    payload = {
        "reason": reason,
        "preferred_media_user_id": preferred_media_user_id,
    }

    inserted = insert_plex_media_job(
        db,
        action="sync",
        vodum_user_id=user_id,
        server_id=server_id,
        library_id=None,
        dedupe_key=dedupe_key,
        payload=payload,
    )

    if inserted:
        task_logger.info(
            f"[MEDIA JOB CREATED] provider=plex action=sync "
            f"user_id={user_id} server_id={server_id} "
            f"preferred_media_user_id={preferred_media_user_id} "
            f"reason={reason}"
        )

    if wake_task:
        try:
            wake_task("apply_plex_access_updates")
        except Exception:
            pass

    return inserted


def force_queue_full_plex_sync_for_user(db, user_id: int, reason: str = "admin_force_resync"):
    """
    RecrÃ©e un job 'sync' complet par serveur Plex liÃ©.

    Important :
    on passe par _insert_plex_media_job() pour annuler proprement
    les anciens jobs actifs du mÃªme user/server, au lieu de supprimer
    brutalement des jobs Ã©ventuellement en cours.
    """
    rows = db.query(
        """
        SELECT
            mu.server_id,
            mu.id AS preferred_media_user_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'plex'
          AND mu.type = 'plex'
        ORDER BY
            mu.server_id ASC,
            CASE WHEN LOWER(COALESCE(mu.role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(mu.accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(mu.external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(mu.role, '')) = 'unfriended' THEN 1 ELSE 0 END ASC,
            mu.id ASC
        """,
        (user_id,),
    ) or []

    queued = 0
    seen_servers = set()

    for row in rows:
        server_id = int(row["server_id"])
        if server_id in seen_servers:
            continue
        seen_servers.add(server_id)

        preferred_media_user_id = (
            int(row["preferred_media_user_id"])
            if row["preferred_media_user_id"] is not None
            else None
        )

        dedupe_key = (
            f"plex:sync:server={server_id}:"
            f"media_user={preferred_media_user_id or 'none'}:admin_force"
        )

        payload = {
            "reason": reason,
            "forced_by_admin": True,
            "preferred_media_user_id": preferred_media_user_id,
        }

        inserted = insert_plex_media_job(
            db,
            action="sync",
            vodum_user_id=user_id,
            server_id=server_id,
            library_id=None,
            dedupe_key=dedupe_key,
            payload=payload,
        )

        if inserted:
            queued += 1

        task_logger.info(
            f"[MEDIA JOB CREATED] provider=plex action=sync "
            f"user_id={user_id} server_id={server_id} "
            f"preferred_media_user_id={preferred_media_user_id} "
            f"inserted={inserted} reason=admin_force"
        )

    return queued

def force_queue_full_jellyfin_sync_for_user(db, user_id: int, reason: str = "admin_force_resync"):
    rows = db.query(
        """
        SELECT DISTINCT
            mu.server_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'jellyfin'
          AND mu.type = 'jellyfin'
        ORDER BY mu.server_id ASC
        """,
        (user_id,),
    ) or []

    queued = 0

    for row in rows:
        server_id = int(row["server_id"])

        dedupe_key = f"jellyfin:sync:server={server_id}:user={user_id}:admin_force"

        payload = {
            "reason": reason,
            "forced_by_admin": True,
        }

        inserted = insert_jellyfin_media_job(
            db,
            action="sync",
            vodum_user_id=user_id,
            server_id=server_id,
            library_id=None,
            dedupe_key=dedupe_key,
            payload=payload,
        )

        if inserted:
            queued += 1

        task_logger.info(
            f"[MEDIA JOB CREATED] provider=jellyfin action=sync "
            f"user_id={user_id} server_id={server_id} "
            f"inserted={inserted} reason=admin_force"
        )

    return queued
