from core.media_jobs import insert_jellyfin_media_job, insert_plex_media_job
from core.user_sync_jobs import get_preferred_plex_media_user_id


def toggle_user_library_access(
    db,
    *,
    user_id: int,
    library_id: int,
    wake_task,
    logger,
) -> dict:
    user = db.query_one("SELECT id, status FROM vodum_users WHERE id = ?", (user_id,))
    if not user:
        return {"ok": False, "reason": "invalid_user"}
    if str(user["status"] or "").strip().lower() == "expired":
        logger.info(
            "[ACCESS REQUEST BLOCKED] user_id=%s library_id=%s reason=expired_user",
            user_id,
            library_id,
        )
        return {"ok": False, "reason": "expired"}

    library = db.query_one(
        "SELECT id, server_id, name FROM libraries WHERE id = ?",
        (library_id,),
    )
    if not library:
        return {"ok": False, "reason": "invalid_library"}
    server = db.query_one(
        "SELECT id, type, name FROM servers WHERE id = ?",
        (library["server_id"],),
    )
    if not server:
        return {"ok": False, "reason": "server_not_found"}

    media_users = db.query(
        "SELECT id FROM media_users WHERE vodum_user_id = ? AND server_id = ?",
        (user_id, library["server_id"]),
    ) or []
    if not media_users:
        return {"ok": False, "reason": "no_media_accounts_for_user"}

    media_user_ids = [int(row["id"]) for row in media_users]
    placeholders = ",".join("?" * len(media_user_ids))
    exists = db.query_one(
        f"""
        SELECT 1 FROM media_user_libraries
        WHERE library_id = ? AND media_user_id IN ({placeholders})
        LIMIT 1
        """,
        (library_id, *media_user_ids),
    )
    removed = bool(exists)
    if removed:
        db.execute(
            f"""
            DELETE FROM media_user_libraries
            WHERE library_id = ? AND media_user_id IN ({placeholders})
            """,
            (library_id, *media_user_ids),
        )
    else:
        for media_user_id in media_user_ids:
            db.execute(
                """
                INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                VALUES (?, ?)
                """,
                (media_user_id, library_id),
            )

    provider = str(server["type"] or "").strip().lower()
    if provider == "plex":
        _queue_plex_access_update(
            db,
            user_id=user_id,
            library=library,
            library_id=library_id,
            media_user_ids=media_user_ids,
            placeholders=placeholders,
            removed=removed,
            logger=logger,
        )
        _wake_worker(
            wake_task,
            "apply_plex_access_updates",
            provider="Plex",
            user_id=user_id,
            server_id=int(library["server_id"]),
            logger=logger,
        )
    elif provider == "jellyfin":
        inserted = insert_jellyfin_media_job(
            db,
            action="sync",
            vodum_user_id=user_id,
            server_id=library["server_id"],
            library_id=None,
            dedupe_key=(
                f"jellyfin:sync:server={library['server_id']}:user={user_id}"
            ),
            payload={
                "reason": "library_toggle",
                "toggled_library_id": library_id,
                "toggled_library_name": library["name"],
                "removed": removed,
            },
        )
        if inserted:
            logger.info(
                "[MEDIA JOB CREATED] provider=jellyfin action=sync "
                "user_id=%s server_id=%s library_id=None",
                user_id,
                library["server_id"],
            )
        _wake_worker(
            wake_task,
            "apply_jellyfin_access_updates",
            provider="Jellyfin",
            user_id=user_id,
            server_id=int(library["server_id"]),
            logger=logger,
        )

    return {
        "ok": True,
        "removed": removed,
        "message": "library_access_removed" if removed else "library_access_added",
    }


def _queue_plex_access_update(
    db,
    *,
    user_id: int,
    library,
    library_id: int,
    media_user_ids: list[int],
    placeholders: str,
    removed: bool,
    logger,
) -> None:
    server_id = int(library["server_id"])
    preferred_media_user_id = get_preferred_plex_media_user_id(db, user_id, server_id)
    remaining = db.query_one(
        f"""
        SELECT COUNT(DISTINCT mul.library_id) AS c
        FROM media_user_libraries mul
        JOIN libraries l ON l.id = mul.library_id
        WHERE mul.media_user_id IN ({placeholders}) AND l.server_id = ?
        """,
        (*media_user_ids, server_id),
    )
    remaining_count = int(remaining["c"] or 0)
    if removed and remaining_count == 0:
        action = "revoke"
        job_library_id = None
        dedupe_key = f"plex:revoke:server={server_id}:user={user_id}"
    elif removed:
        action = "sync"
        job_library_id = None
        dedupe_key = f"plex:sync:server={server_id}:user={user_id}"
    else:
        action = "grant"
        job_library_id = library_id
        dedupe_key = (
            f"plex:grant:server={server_id}:user={user_id}:lib={library_id}"
        )
    inserted = insert_plex_media_job(
        db,
        action=action,
        vodum_user_id=user_id,
        server_id=server_id,
        library_id=job_library_id,
        dedupe_key=dedupe_key,
        payload={
            "reason": "library_toggle",
            "library_id": library_id,
            "library_name": library["name"],
            "removed": removed,
            "remaining_count": remaining_count,
            "preferred_media_user_id": preferred_media_user_id,
        },
    )
    if inserted:
        logger.info(
            "[MEDIA JOB CREATED] provider=plex action=%s user_id=%s "
            "server_id=%s library_id=%s preferred_media_user_id=%s",
            action,
            user_id,
            server_id,
            job_library_id,
            preferred_media_user_id,
        )


def _wake_worker(wake_task, task_name, *, provider, user_id, server_id, logger):
    try:
        wake_task(task_name)
    except Exception:
        logger.exception(
            "%s access job persisted but worker startup failed | "
            "user_id=%s | server_id=%s",
            provider,
            user_id,
            server_id,
        )
