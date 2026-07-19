from __future__ import annotations

import json
from datetime import datetime, timezone

from core.plex_sync_api import fetch_admin_account_from_token
from logging_utils import get_logger, is_debug_mode_enabled


log = get_logger("plex_owner_sync")


def sync_plex_owner_for_server(db, server):
    log.info("[OWNER] Sync owner for server %s", server["name"])
    token = (server["token"] or "").strip()
    if not token:
        log.warning("[OWNER] %s: no token", server["name"])
        return
    owner = fetch_admin_account_from_token(token)
    if not owner:
        log.error("[OWNER] %s: Unable to retrieve the owner", server["name"])
        return

    plex_id = owner["plex_id"]
    username = owner.get("username") or f"user_{plex_id}"
    email = owner.get("email")
    avatar = owner.get("avatar")
    today = datetime.now(timezone.utc).date().isoformat()

    identity = db.query_one(
        """
        SELECT vodum_user_id
        FROM user_identities
        WHERE type = 'plex'
          AND server_id IS NULL
          AND external_user_id = ?
        """,
        (plex_id,),
    )
    if identity:
        vodum_user_id = identity["vodum_user_id"]
    else:
        existing_user = (
            db.query_one(
                "SELECT id FROM vodum_users WHERE lower(email) = lower(?)",
                (email,),
            )
            if email
            else None
        )
        if existing_user:
            vodum_user_id = existing_user["id"]
            db.execute(
                """
                UPDATE vodum_users
                SET username = COALESCE(username, ?)
                WHERE id = ?
                """,
                (username, int(vodum_user_id)),
            )
        else:
            columns = "username, email, created_at, status" if email else "username, created_at, status"
            placeholders = "?, ?, ?, 'active'" if email else "?, ?, 'active'"
            values = (username, email, today) if email else (username, today)
            vodum_user_id = db.execute(
                f"""
                INSERT INTO vodum_users({columns})
                VALUES ({placeholders})
                """,
                values,
            ).lastrowid

    db.execute(
        """
        INSERT OR IGNORE INTO user_identities(
            vodum_user_id, type, server_id, external_user_id
        )
        VALUES (?, 'plex', NULL, ?)
        """,
        (vodum_user_id, plex_id),
    )
    media_user = db.query_one(
        """
        SELECT id, details_json
        FROM media_users
        WHERE server_id = ?
          AND type = 'plex'
          AND external_user_id = ?
        """,
        (server["id"], plex_id),
    )
    owner_share = {
        "allowSync": 1,
        "allowCameraUpload": 1,
        "allowChannels": 1,
        "filterMovies": "",
        "filterTelevision": "",
        "filterMusic": "",
    }
    if media_user:
        try:
            details = json.loads(media_user["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}
        share = details.get("plex_share", {})
        if not isinstance(share, dict):
            share = {}
        share.update(owner_share)
        details["plex_share"] = share
        db.execute(
            """
            UPDATE media_users
            SET vodum_user_id = ?, username = ?, email = ?, avatar = ?,
                role = 'owner', details_json = ?
            WHERE id = ?
            """,
            (
                vodum_user_id,
                username,
                email,
                avatar,
                json.dumps(details, ensure_ascii=False),
                media_user["id"],
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO media_users(
                server_id, vodum_user_id, external_user_id, username,
                email, avatar, type, role, details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 'plex', 'owner', ?)
            """,
            (
                server["id"],
                vodum_user_id,
                plex_id,
                username,
                email,
                avatar,
                json.dumps({"plex_share": owner_share}, ensure_ascii=False),
            ),
        )
    db.execute(
        """
        UPDATE vodum_users
        SET expiration_date_override = 1
        WHERE id = ?
        """,
        (vodum_user_id,),
    )
    if is_debug_mode_enabled():
        log.debug(
            "[OWNER] %s: owner OK (plex_id=%s, vodum_user_id=%s)",
            server["name"],
            plex_id,
            vodum_user_id,
        )
