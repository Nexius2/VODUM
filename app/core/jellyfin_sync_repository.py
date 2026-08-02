import json


def upsert_jellyfin_library(db, server_id, section_id, name, library_type) -> int:
    db.execute(
        """
        INSERT INTO libraries (server_id, section_id, name, type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(server_id, section_id) DO UPDATE SET
            name = excluded.name, type = excluded.type
        """,
        (server_id, section_id, name, library_type),
    )
    row = db.query_one(
        "SELECT id FROM libraries WHERE server_id = ? AND section_id = ?",
        (server_id, section_id),
    )
    return int(row["id"])


def set_jellyfin_media_user_state(
    db, media_user_id: int, server_id: int, owned: int,
    all_libraries: int, num_libraries: int, last_seen_at,
):
    details = {
        "owned": int(owned), "all_libraries": int(all_libraries),
        "num_libraries": int(num_libraries), "pending": 0,
        "last_seen_at": last_seen_at, "source": "jellyfin_api",
        "server_id": int(server_id),
    }
    db.execute(
        "UPDATE media_users SET details_json = ? WHERE id = ?",
        (json.dumps(details, ensure_ascii=False), media_user_id),
    )


def replace_jellyfin_library_access(
    db, media_user_id: int, server_id: int, allowed_library_ids: list[int],
):
    db.execute(
        """
        DELETE FROM media_user_libraries
        WHERE media_user_id = ?
          AND library_id IN (SELECT id FROM libraries WHERE server_id = ?)
        """,
        (media_user_id, server_id),
    )
    for library_id in allowed_library_ids:
        db.execute(
            """INSERT OR IGNORE INTO media_user_libraries (media_user_id, library_id)
            VALUES (?, ?)""",
            (media_user_id, library_id),
        )
