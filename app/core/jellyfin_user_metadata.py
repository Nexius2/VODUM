import json
from typing import Any


def extract_joined_at(detail: dict[str, Any]) -> str | None:
    for key in ("DateCreated", "CreatedDate", "CreatedAt", "CreationDate", "DateCreatedUtc"):
        value = detail.get(key)
        if value:
            return str(value)
    return None


def extract_role(policy: dict[str, Any]) -> str | None:
    if not isinstance(policy, dict):
        return None
    return "admin" if policy.get("IsAdministrator") else "user"


def extract_avatar_path(user_id: str, detail: dict[str, Any]) -> str | None:
    tag = detail.get("PrimaryImageTag")
    return f"/Users/{user_id}/Images/Primary?tag={tag}" if tag else None


def store_user_metadata(db, media_user_id: int, user_id: str, detail: dict):
    detail = detail if isinstance(detail, dict) else {}
    policy = detail.get("Policy") if isinstance(detail.get("Policy"), dict) else {}
    db.execute(
        """
        UPDATE media_users
        SET raw_json = ?, role = COALESCE(?, role),
            joined_at = COALESCE(?, joined_at), avatar = COALESCE(?, avatar)
        WHERE id = ?
        """,
        (json.dumps(detail, ensure_ascii=False), extract_role(policy),
         extract_joined_at(detail), extract_avatar_path(user_id, detail), media_user_id),
    )
