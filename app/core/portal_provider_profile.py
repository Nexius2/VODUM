from __future__ import annotations

from core.providers.jellyfin_users import jellyfin_update_username


def update_portal_provider_profile(db, vodum_user_id: int, media_user_id: int, username: str) -> dict:
    normalized = str(username or "").strip()
    if not normalized or len(normalized) > 100:
        raise ValueError("portal_provider_username_invalid")
    row = db.query_one(
        """
        SELECT mu.id,mu.type,mu.external_user_id,mu.username,
               s.id AS server_id,s.name,s.type AS server_type,s.url,s.local_url,s.public_url,
               s.token,s.settings_json
        FROM media_users mu JOIN servers s ON s.id=mu.server_id
        WHERE mu.id=? AND mu.vodum_user_id=?
        """, (int(media_user_id), int(vodum_user_id)),
    )
    if not row:
        raise ValueError("portal_media_account_missing")
    account = dict(row)
    if str(account.get("type") or "").lower() != "jellyfin":
        raise ValueError("portal_provider_profile_readonly")
    if not str(account.get("external_user_id") or "").strip():
        raise ValueError("portal_media_account_missing")
    if str(account.get("username") or "").strip() == normalized:
        return {"changed": False, "media_user_id": int(media_user_id)}
    changed = jellyfin_update_username(account, str(account["external_user_id"]), normalized)
    if changed:
        db.execute("UPDATE media_users SET username=? WHERE id=? AND vodum_user_id=?", (normalized, int(media_user_id), int(vodum_user_id)))
    return {"changed": changed, "media_user_id": int(media_user_id)}
