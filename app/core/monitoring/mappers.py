from __future__ import annotations
from typing import Optional
import json


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
    Never infer ownership from display names or from another server's IDs.
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
