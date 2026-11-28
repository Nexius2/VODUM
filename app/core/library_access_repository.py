"""Store provider library grants for one media account and server."""

import sqlite3

_SERVER_LIBRARY_ACCESS = """
    SELECT mul.library_id
    FROM media_user_libraries mul
    JOIN libraries l ON l.id = mul.library_id
    WHERE mul.media_user_id = ?
      AND l.server_id = ?
"""


def get_media_user_library_ids_for_server(db, media_user_id: int, server_id: int) -> set[int]:
    rows = db.query(_SERVER_LIBRARY_ACCESS, (media_user_id, server_id)) or []
    return {int(row["library_id"]) for row in rows if row["library_id"] is not None}


def apply_media_user_library_diff_for_server(
    db, media_user_id: int, server_id: int, desired_library_ids: set[int],
):
    with db.transaction() as cursor:
        cursor.execute(_SERVER_LIBRARY_ACCESS, (media_user_id, server_id))
        current = {int(row["library_id"]) for row in cursor.fetchall()}
        to_add = sorted(desired_library_ids - current)
        to_remove = sorted(current - desired_library_ids)
        if to_add:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO media_user_libraries (media_user_id, library_id)
                VALUES (?, ?)
                """,
                [(media_user_id, library_id) for library_id in to_add],
            )
        if to_remove:
            cursor.executemany(
                "DELETE FROM media_user_libraries WHERE media_user_id = ? AND library_id = ?",
                [(media_user_id, library_id) for library_id in to_remove],
            )
    return current, to_add, to_remove


def prune_missing_libraries(db, server_id, existing_libraries, current_ids):
    """Prune each missing library atomically with its grants."""
    retained = []
    for row in existing_libraries:
        library_id = int(row["id"])
        if library_id in current_ids:
            continue
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    """
                    DELETE FROM media_user_libraries
                    WHERE library_id IN (SELECT id FROM libraries WHERE id = ? AND server_id = ?)
                    """,
                    (library_id, server_id),
                )
                cursor.execute(
                    "DELETE FROM libraries WHERE id = ? AND server_id = ?",
                    (library_id, server_id),
                )
        except sqlite3.IntegrityError as exc:
            if str(exc) != "FOREIGN KEY constraint failed":
                raise
            retained.append(row["name"])
    return retained
