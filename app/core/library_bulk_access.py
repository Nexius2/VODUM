"""Bulk grant/remove helpers for library access actions."""

from __future__ import annotations

import json

try:
    from core.media_jobs import insert_plex_media_job
except ModuleNotFoundError:  # pragma: no cover - direct package imports in tests
    from app.core.media_jobs import insert_plex_media_job


class BulkAccessError(ValueError):
    def __init__(self, flash_key: str, category: str = "error"):
        super().__init__(flash_key)
        self.flash_key = flash_key
        self.category = category


def normalize_library_ids(values, *, limit: int = 500) -> list[int]:
    """Return unique positive library ids, preserving first-seen order up to limit."""
    out: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise BulkAccessError("invalid_library")
        if parsed <= 0 or parsed in seen:
            continue
        seen.add(parsed)
        out.append(parsed)
        if len(out) >= limit:
            break
    return out


def _get_server(db, server_id: int):
    server = db.query_one("SELECT id, name, type FROM servers WHERE id = ?", (server_id,))
    if not server:
        raise BulkAccessError("server_not_found")
    if server["type"] != "plex":
        raise BulkAccessError("sync_not_supported_for_server_type", "warning")
    return server


def _valid_library_ids(db, server_id: int, library_ids: list[int]) -> list[int]:
    if not server_id or not library_ids:
        raise BulkAccessError("no_server_or_library_selected")
    placeholders = ",".join("?" * len(library_ids))
    rows = db.query(
        f"""
        SELECT id
        FROM libraries
        WHERE server_id = ?
          AND id IN ({placeholders})
        """,
        (server_id, *library_ids),
    )
    valid = [int(row["id"]) for row in (rows or [])]
    if not valid:
        raise BulkAccessError("no_valid_libraries_for_server")
    return valid


def _preferred_plex_media_user_id(db, vodum_user_id: int, server_id: int) -> int | None:
    row = db.query_one(
        """
        SELECT id
        FROM media_users
        WHERE vodum_user_id = ?
          AND server_id = ?
          AND type = 'plex'
        ORDER BY
            CASE WHEN LOWER(COALESCE(role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(role, '')) = 'unfriended' THEN 1 ELSE 0 END ASC,
            id ASC
        LIMIT 1
        """,
        (vodum_user_id, server_id),
    )
    return int(row["id"]) if row and row["id"] is not None else None


def _is_pending_plex_invite(row) -> bool:
    accepted_at = str(row["accepted_at"] or "").strip()
    if accepted_at:
        return False
    details_json = {}
    try:
        details_json = json.loads(row["details_json"]) if row["details_json"] else {}
    except Exception:
        details_json = {}
    invite_state = (details_json.get("plex_invite_state") or {}) if isinstance(details_json, dict) else {}
    return bool(invite_state.get("is_pending")) or (
        not str(row["external_user_id"] or "").strip()
        and bool(str(row["email"] or "").strip() or str(row["username"] or "").strip())
    )


def grant_libraries_to_active_users(db, *, server_id: int, library_ids, insert_job=insert_plex_media_job) -> dict:
    server_id = int(server_id or 0)
    normalized_ids = normalize_library_ids(library_ids)
    server = _get_server(db, server_id)
    valid_library_ids = _valid_library_ids(db, server_id, normalized_ids)

    users = db.query(
        """
        SELECT
            mu.id AS media_user_id,
            mu.vodum_user_id AS vodum_user_id,
            mu.username,
            mu.email,
            mu.external_user_id,
            mu.accepted_at,
            mu.details_json,
            mu.role
        FROM media_users mu
        JOIN vodum_users vu
            ON vu.id = mu.vodum_user_id
        WHERE mu.server_id = ?
          AND mu.type = 'plex'
          AND vu.status = 'active'
          AND mu.vodum_user_id IS NOT NULL
          AND LOWER(COALESCE(mu.role, '')) != 'owner'
        ORDER BY mu.username
        """,
        (server_id,),
    ) or []
    if not users:
        raise BulkAccessError("no_active_users_for_server", "warning")

    inserted_links = 0
    for library_id in valid_library_ids:
        for user in users:
            cur = db.execute(
                """
                INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                VALUES (?, ?)
                """,
                (user["media_user_id"], library_id),
            )
            inserted_links += max(0, int(getattr(cur, "rowcount", 0) or 0))

    pending_count = sum(1 for user in users if _is_pending_plex_invite(user))
    ready_count = len(users) - pending_count
    queued_jobs = 0

    for vodum_user_id in sorted({int(user["vodum_user_id"]) for user in users if user["vodum_user_id"] is not None}):
        preferred_media_user_id = _preferred_plex_media_user_id(db, vodum_user_id, server_id)
        inserted = insert_job(
            db,
            action="sync",
            vodum_user_id=vodum_user_id,
            server_id=server_id,
            dedupe_key=f"plex:sync:server={server_id}:media_user={preferred_media_user_id or 'none'}:bulk_grant",
            payload={
                "reason": "bulk_grant",
                "library_ids": valid_library_ids,
                "preferred_media_user_id": preferred_media_user_id,
            },
        )
        if inserted:
            queued_jobs += 1

    return {
        "server_name": server["name"],
        "library_count": len(valid_library_ids),
        "user_count": len(users),
        "inserted_links": inserted_links,
        "ready_count": ready_count,
        "pending_count": pending_count,
        "queued_jobs": queued_jobs,
        "message": (
            f"Grant access done on {server['name']}: "
            f"{len(valid_library_ids)} librar{'y' if len(valid_library_ids) == 1 else 'ies'}, "
            f"{len(users)} active user(s), {inserted_links} DB link(s) added. "
            f"Ready Plex sync: {ready_count}. Pending Plex invites: {pending_count}."
        ),
    }


def remove_libraries_from_users(db, *, server_id: int, library_ids, insert_job=insert_plex_media_job) -> dict:
    server_id = int(server_id or 0)
    normalized_ids = normalize_library_ids(library_ids)
    server = _get_server(db, server_id)
    valid_library_ids = _valid_library_ids(db, server_id, normalized_ids)

    users = db.query(
        """
        SELECT
            mu.id AS media_user_id,
            mu.vodum_user_id AS vodum_user_id,
            mu.username,
            mu.role
        FROM media_users mu
        WHERE mu.server_id = ?
          AND mu.type = 'plex'
          AND LOWER(COALESCE(mu.role, '')) != 'owner'
        ORDER BY mu.username
        """,
        (server_id,),
    ) or []
    if not users:
        raise BulkAccessError("No removable Plex users found for this server.", "warning")

    media_user_ids = [int(user["media_user_id"]) for user in users]
    media_placeholders = ",".join("?" * len(media_user_ids))
    libs_placeholders = ",".join("?" * len(valid_library_ids))
    cur = db.execute(
        f"""
        DELETE FROM media_user_libraries
        WHERE media_user_id IN ({media_placeholders})
          AND library_id IN ({libs_placeholders})
        """,
        (*media_user_ids, *valid_library_ids),
    )
    deleted_links = max(0, int(getattr(cur, "rowcount", 0) or 0))
    if deleted_links <= 0:
        raise BulkAccessError(
            f"No existing DB access found to remove on {server['name']} for the selected librar"
            f"{'y' if len(valid_library_ids) == 1 else 'ies'}.",
            "warning",
        )

    queued_sync = 0
    queued_revoke = 0
    for vodum_user_id in sorted({int(user["vodum_user_id"]) for user in users if user["vodum_user_id"] is not None}):
        preferred_media_user_id = _preferred_plex_media_user_id(db, vodum_user_id, server_id)
        if not preferred_media_user_id:
            continue
        remaining = db.query_one(
            """
            SELECT COUNT(DISTINCT mul.library_id) AS c
            FROM media_user_libraries mul
            JOIN libraries l
                ON l.id = mul.library_id
            WHERE mul.media_user_id = ?
              AND l.server_id = ?
            """,
            (preferred_media_user_id, server_id),
        )
        remaining_count = int(remaining["c"]) if remaining and remaining["c"] is not None else 0
        action = "revoke" if remaining_count == 0 else "sync"
        if action == "revoke":
            queued_revoke += 1
        else:
            queued_sync += 1
        insert_job(
            db,
            action=action,
            vodum_user_id=vodum_user_id,
            server_id=server_id,
            dedupe_key=f"plex:{action}:server={server_id}:media_user={preferred_media_user_id}:bulk_remove",
            payload={
                "reason": "bulk_remove",
                "library_ids": valid_library_ids,
                "remaining_count": remaining_count,
                "preferred_media_user_id": preferred_media_user_id,
            },
        )

    return {
        "server_name": server["name"],
        "library_count": len(valid_library_ids),
        "deleted_links": deleted_links,
        "queued_sync": queued_sync,
        "queued_revoke": queued_revoke,
        "message": (
            f"Remove access done on {server['name']}: "
            f"{len(valid_library_ids)} librar{'y' if len(valid_library_ids) == 1 else 'ies'}, "
            f"{deleted_links} DB link(s) removed, {queued_sync} sync job(s), {queued_revoke} revoke job(s)."
        ),
    }
