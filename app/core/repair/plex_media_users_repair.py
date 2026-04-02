import json

REPAIR_KEY = "plex_media_users_repair_v1"


def _pick_canonical_row(rows):
    """
    Garde la meilleure ligne pour un couple (vodum_user_id, server_id).
    Priorité :
    1. accepted_at rempli
    2. external_user_id rempli
    3. type != 'unfriend'
    4. plus petit id
    """
    def sort_key(r):
        accepted = 0 if str(r["accepted_at"] or "").strip() else 1
        external = 0 if str(r["external_user_id"] or "").strip() else 1
        unfriend = 1 if str(r["type"] or "").strip().lower() == "unfriend" else 0
        return (accepted, external, unfriend, int(r["id"]))

    return sorted(rows, key=sort_key)[0]


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
        "SELECT * FROM app_repairs WHERE key = ?",
        (REPAIR_KEY,),
    )

    if row and row["status"] == "done":
        logger.info("[REPAIR] plex_media_users_repair_v1 already done, skipping")
        return

    logger.warning("[REPAIR] START plex_media_users_repair_v1")

    db.execute(
        """
        INSERT OR REPLACE INTO app_repairs(key, status, started_at, finished_at, details_json)
        VALUES (?, 'running', datetime('now'), NULL, NULL)
        """,
        (REPAIR_KEY,),
    )

    stats = {
        "duplicate_groups": 0,
        "media_users_deleted": 0,
        "media_user_libraries_relinked": 0,
        "media_user_libraries_deduped": 0,
        "indexes_created": 0,
    }

    try:
        duplicate_groups = db.query(
            """
            SELECT vodum_user_id, server_id, COUNT(*) AS c
            FROM media_users
            WHERE vodum_user_id IS NOT NULL
            GROUP BY vodum_user_id, server_id
            HAVING COUNT(*) > 1
            ORDER BY server_id, vodum_user_id
            """
        )

        stats["duplicate_groups"] = len(duplicate_groups)

        for grp in duplicate_groups:
            vodum_user_id = grp["vodum_user_id"]
            server_id = grp["server_id"]

            rows = db.query(
                """
                SELECT *
                FROM media_users
                WHERE vodum_user_id = ?
                  AND server_id = ?
                ORDER BY id ASC
                """,
                (vodum_user_id, server_id),
            )

            if len(rows) < 2:
                continue

            good = _pick_canonical_row(rows)
            bad_rows = [r for r in rows if int(r["id"]) != int(good["id"])]

            for bad in bad_rows:
                bad_id = int(bad["id"])
                good_id = int(good["id"])

                # 1) rattacher les libraries sans créer de doublons
                libs = db.query(
                    "SELECT library_id FROM media_user_libraries WHERE media_user_id = ?",
                    (bad_id,),
                )

                for lib in libs:
                    lib_id = int(lib["library_id"])
                    exists = db.query_one(
                        """
                        SELECT 1
                        FROM media_user_libraries
                        WHERE media_user_id = ?
                          AND library_id = ?
                        """,
                        (good_id, lib_id),
                    )
                    if not exists:
                        db.execute(
                            """
                            INSERT INTO media_user_libraries(media_user_id, library_id)
                            VALUES (?, ?)
                            """,
                            (good_id, lib_id),
                        )
                        stats["media_user_libraries_relinked"] += 1

                # 2) supprimer les anciennes liaisons libraries
                db.execute(
                    "DELETE FROM media_user_libraries WHERE media_user_id = ?",
                    (bad_id,),
                )

                # 3) supprimer la mauvaise ligne media_users
                db.execute(
                    "DELETE FROM media_users WHERE id = ?",
                    (bad_id,),
                )
                stats["media_users_deleted"] += 1

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

        # Index anti-doublon définitif
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_media_users_vodum_server
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