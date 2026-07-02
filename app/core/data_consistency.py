"""Conservative repairs for structurally impossible database relationships."""

from __future__ import annotations


def audit_access_consistency(db) -> dict[str, int]:
    orphan_media_users = db.query_one(
        """
        SELECT COUNT(*) AS count
        FROM media_user_libraries mul
        LEFT JOIN media_users mu ON mu.id = mul.media_user_id
        WHERE mu.id IS NULL
        """
    )
    orphan_libraries = db.query_one(
        """
        SELECT COUNT(*) AS count
        FROM media_user_libraries mul
        LEFT JOIN libraries l ON l.id = mul.library_id
        WHERE l.id IS NULL
        """
    )
    cross_server = db.query_one(
        """
        SELECT COUNT(*) AS count
        FROM media_user_libraries mul
        JOIN media_users mu ON mu.id = mul.media_user_id
        JOIN libraries l ON l.id = mul.library_id
        WHERE mu.server_id <> l.server_id
        """
    )
    return {
        "orphan_media_users": int(orphan_media_users["count"] or 0),
        "orphan_libraries": int(orphan_libraries["count"] or 0),
        "cross_server": int(cross_server["count"] or 0),
    }


def repair_access_consistency(db) -> dict[str, int]:
    """Remove only access rows that cannot represent a valid provider relationship."""
    before = audit_access_consistency(db)
    cursor = db.execute(
        """
        DELETE FROM media_user_libraries
        WHERE media_user_id NOT IN (SELECT id FROM media_users)
           OR library_id NOT IN (SELECT id FROM libraries)
           OR EXISTS (
               SELECT 1
               FROM media_users mu
               JOIN libraries l ON l.id = media_user_libraries.library_id
               WHERE mu.id = media_user_libraries.media_user_id
                 AND mu.server_id <> l.server_id
           )
        """
    )
    deleted = max(0, int(getattr(cursor, "rowcount", 0) or 0))
    after = audit_access_consistency(db)
    return {"deleted": deleted, **before, "remaining": sum(after.values())}
