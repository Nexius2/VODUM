import json

REPAIR_KEY = "plex_media_users_repair_v1"





def run_repair_if_needed(db, logger):
    # Sécurité : la table doit exister même sur une vieille DB
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS app_repairs (
            key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            details_json TEXT
        )
        """
    )

    row = db.query_one(
        "SELECT key, status, started_at, finished_at, details_json FROM app_repairs WHERE key = ?",
        (REPAIR_KEY,),
    )

    if row and row["status"] == "done":
        logger.info("[REPAIR] plex_media_users_repair_v1 already done, skipping")
        return {
            "status": "skipped",
            "repair_key": REPAIR_KEY,
            "reason": "already_done",
        }

    logger.warning("[REPAIR] START plex_media_users_repair_v1")

    db.execute(
        """
        INSERT OR REPLACE INTO app_repairs(key, status, started_at, finished_at, details_json)
        VALUES (?, 'running', datetime('now'), NULL, NULL)
        """,
        (REPAIR_KEY,),
    )

    stats = {
        "media_user_libraries_deduped": 0,
        "indexes_created": 0,
    }

    try:
        # Dédoublonnage sécurité sur media_user_libraries
        before = db.query_one(
            """
            SELECT COUNT(*) AS c
            FROM (
                SELECT media_user_id, library_id, COUNT(*) AS cc
                FROM media_user_libraries
                GROUP BY media_user_id, library_id
                HAVING COUNT(*) > 1
            ) x
            """
        )
        before_count = int(before["c"]) if before and "c" in before.keys() else 0

        db.execute(
            """
            DELETE FROM media_user_libraries
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM media_user_libraries
                GROUP BY media_user_id, library_id
            )
            """
        )

        stats["media_user_libraries_deduped"] = before_count

        db.execute("DROP INDEX IF EXISTS uq_media_users_vodum_server")
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_media_users_vodum_server
            ON media_users(vodum_user_id, server_id)
            WHERE vodum_user_id IS NOT NULL
            """
        )
        stats["indexes_created"] += 1

        db.execute(
            """
            UPDATE app_repairs
            SET status = 'done',
                finished_at = datetime('now'),
                details_json = ?
            WHERE key = ?
            """,
            (json.dumps(stats, ensure_ascii=False), REPAIR_KEY),
        )

        logger.warning(f"[REPAIR] DONE plex_media_users_repair_v1 {stats}")

        return {
            "status": "done",
            "repair_key": REPAIR_KEY,
            "stats": stats,
        }

    except Exception as e:
        db.execute(
            """
            UPDATE app_repairs
            SET status = 'failed',
                finished_at = datetime('now'),
                details_json = ?
            WHERE key = ?
            """,
            (json.dumps({"error": str(e)}, ensure_ascii=False), REPAIR_KEY),
        )
        logger.exception("[REPAIR] FAILED plex_media_users_repair_v1")
        raise