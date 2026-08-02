from core.media_jobs import insert_plex_media_job
from core.user_sync_jobs import get_preferred_plex_media_user_id
from tasks_engine import enable_and_run_task_by_name


def load_sync_server(db, server_id: int):
    return db.query_one(
        "SELECT id, type FROM servers WHERE id = ?",
        (server_id,),
    )


def load_plex_sync_user_ids(db, server_id: int):
    return db.query(
        """
        SELECT DISTINCT vu.id AS vodum_user_id
        FROM vodum_users vu
        JOIN media_users mu
            ON mu.vodum_user_id = vu.id
        JOIN media_user_libraries mul
            ON mul.media_user_id = mu.id
        JOIN libraries l
            ON l.id = mul.library_id
        WHERE mu.server_id = ?
          AND l.server_id = ?
          AND mu.type = 'plex'
        """,
        (server_id, server_id),
    )


def build_plex_server_sync_job(server_id: int, preferred_media_user_id):
    dedupe_key = (
        f"plex:sync:server={server_id}:"
        f"media_user={preferred_media_user_id or 'none'}:server_sync"
    )
    payload = {
        "reason": "server_sync",
        "preferred_media_user_id": preferred_media_user_id,
    }
    return dedupe_key, payload


def enqueue_plex_server_sync_jobs(db, server_id: int, vodum_users) -> int:
    created = 0
    for row in vodum_users:
        vodum_user_id = int(row["vodum_user_id"])
        preferred_media_user_id = get_preferred_plex_media_user_id(
            db, vodum_user_id, server_id,
        )
        dedupe_key, payload = build_plex_server_sync_job(
            server_id, preferred_media_user_id,
        )
        inserted = insert_plex_media_job(
            db,
            action="sync",
            vodum_user_id=vodum_user_id,
            server_id=server_id,
            dedupe_key=dedupe_key,
            payload=payload,
        )
        if inserted:
            created += 1
    return created


def wake_plex_sync_worker() -> bool:
    try:
        enable_and_run_task_by_name("apply_plex_access_updates")
    except Exception:
        return False
    return True


def plex_sync_result_flash(created: int) -> tuple[str, str]:
    if created > 0:
        return "sync_jobs_created", "success"
    return "sync_jobs_already_pending", "info"
