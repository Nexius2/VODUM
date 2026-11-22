import json
from datetime import datetime, timezone

from core.library_access_repository import apply_media_user_library_diff_for_server, prune_missing_libraries


def set_jellyfin_media_user_presence(
    db, media_user_id: int, external_user_id: str, presence: str,
) -> None:
    row = db.query_one("SELECT details_json FROM media_users WHERE id = ?", (int(media_user_id),))
    details = {}
    if row and row["details_json"]:
        try:
            parsed = json.loads(row["details_json"])
            if isinstance(parsed, dict):
                details = parsed
        except (TypeError, ValueError):
            pass
    details.update({
        "provider_presence": str(presence),
        "provider_presence_external_user_id": str(external_user_id or ""),
        "provider_presence_checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    db.execute(
        "UPDATE media_users SET details_json = ? WHERE id = ?",
        (json.dumps(details, ensure_ascii=False), int(media_user_id)),
    )
    from core.portal_provider_identity_state import reconcile_portal_provider_identity
    reconcile_portal_provider_identity(db, int(media_user_id))


def mark_jellyfin_media_user_removed(db, media_user_id: int, external_user_id: str) -> None:
    set_jellyfin_media_user_presence(db, media_user_id, external_user_id, "removed")


def mark_jellyfin_media_user_present(db, media_user_id: int, external_user_id: str) -> None:
    set_jellyfin_media_user_presence(db, media_user_id, external_user_id, "present")


def upsert_jellyfin_library(db, server_id, section_id, name, library_type) -> int:
    db.execute(
        """
        INSERT INTO libraries (server_id, section_id, name, type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(server_id, section_id) DO UPDATE SET
            name = excluded.name, type = excluded.type
        WHERE libraries.name IS NOT excluded.name
           OR libraries.type IS NOT excluded.type
        """,
        (server_id, section_id, name, library_type),
    )
    row = db.query_one(
        "SELECT id FROM libraries WHERE server_id = ? AND section_id = ?",
        (server_id, section_id),
    )
    return int(row["id"])


def prune_jellyfin_libraries(db, server_id, current_ids):
    """Remove stale libraries while preserving rows referenced by configurations."""
    existing = db.query("SELECT id, name FROM libraries WHERE server_id = ?", (server_id,))
    return prune_missing_libraries(db, server_id, existing, current_ids)


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
    apply_media_user_library_diff_for_server(db, media_user_id, server_id, set(allowed_library_ids))
