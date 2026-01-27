from __future__ import annotations
from typing import Optional

def resolve_media_user_id(
    db,
    server_id: int,
    provider: str,
    external_user_id: Optional[str],
    username: Optional[str] = None,
) -> Optional[int]:
    # 1) match by external_user_id (best)
    if external_user_id:
        row = db.query_one(
            """
            SELECT id
            FROM media_users
            WHERE server_id = ?
              AND type = ?
              AND external_user_id = ?
            LIMIT 1
            """,
            (server_id, provider, str(external_user_id)),
        )
        if row:
            return int(row["id"])

    # 2) fallback by username
    if username:
        row = db.query_one(
            """
            SELECT id
            FROM media_users
            WHERE server_id = ?
              AND type = ?
              AND username = ?
            LIMIT 1
            """,
            (server_id, provider, str(username)),
        )
        if row:
            return int(row["id"])

    return None
