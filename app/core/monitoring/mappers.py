from __future__ import annotations
from typing import Optional
import json


def _plex_owner_for_local_id(db, server_id):
    return db.query_one(
        """
        SELECT MIN(id) AS id, MIN(username) AS username
        FROM media_users
        WHERE server_id = ? AND type = 'plex' AND role = 'owner'
        HAVING COUNT(*) = 1 AND COUNT(vodum_user_id) = 1
           AND NULLIF(TRIM(MIN(username)), '') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM media_users
               WHERE server_id = ? AND type = 'plex' AND external_user_id = '1'
           )
        """,
        (server_id, server_id),
    )


def apply_playback_username(session):
    """Show Plex's reported name while synchronization is still pending."""
    if str(session.get('username') or '').strip() not in ('', '-'):
        return
    try:
        raw = session.get('raw_json') or '{}'
        raw = json.loads(raw) if isinstance(raw, str) else raw
        user = raw.get('User') or {}
        name = str(user.get('title') or user.get('username') or '').strip()
        if name and name != '-':
            session['username'] = name
    except (ValueError, TypeError, AttributeError):
        pass

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

    if provider == "plex" and str(external_user_id) == "1" and username:
        owner = _plex_owner_for_local_id(db, server_id)
        if owner and str(owner["username"] or "").strip().casefold() == str(username).strip().casefold():
            return int(owner["id"])

    # 2) fallback by username
    if username and str(username).strip() not in ('-', ''):
        row = db.query_one(
            """
            SELECT id
            FROM media_users
            WHERE server_id = ?
              AND type = ?
              AND LOWER(TRIM(username)) = LOWER(TRIM(?))
              AND (NULLIF(TRIM(external_user_id), '') IS NULL OR external_user_id = ?)
            LIMIT 1
            """,
            (server_id, provider, str(username), str(external_user_id or '')),
        )
        if row:
            return int(row["id"])

    return None


def repair_unmapped_sessions(db, server_id: int) -> None:
    """Recover playback collected before the provider account was synchronized.

    Only an unambiguous provider ID on the same server is authoritative.
    Plex's local owner ID also requires the name of the unique synced owner.
    """
    for table in ('media_sessions', 'media_session_history', 'media_events'):
        db.execute(f"""
            UPDATE OR IGNORE {table} AS playback
            SET media_user_id = (
                SELECT MIN(mu.id) FROM media_users mu
                WHERE mu.server_id = playback.server_id
                  AND mu.type = playback.provider
                  AND mu.external_user_id = playback.external_user_id
            )
            WHERE playback.server_id = ? AND playback.media_user_id IS NULL
              AND NULLIF(TRIM(playback.external_user_id), '') IS NOT NULL
              AND 1 = (
                SELECT COUNT(*) FROM media_users mu
                WHERE mu.server_id = playback.server_id
                  AND mu.type = playback.provider
                  AND mu.external_user_id = playback.external_user_id
              )
        """, (server_id,))

    owner = _plex_owner_for_local_id(db, server_id)
    if not owner:
        return
    for table in ("media_sessions", "media_session_history"):
        db.execute(f"""
            UPDATE OR IGNORE {table}
            SET media_user_id = ?
            WHERE server_id = ? AND provider = 'plex' AND media_user_id IS NULL
              AND external_user_id = '1'
              AND CASE WHEN json_valid(raw_json) THEN
                    CAST(json_extract(raw_json, '$.User.id') AS TEXT) = '1'
                    AND LOWER(TRIM(json_extract(raw_json, '$.User.title'))) = LOWER(TRIM(?))
                  ELSE 0 END
        """, (owner["id"], server_id, owner["username"]))
