from typing import Optional

from core.stream_policy_utils import actor_key


def log_enforcement(
    db, policy_id: int, server_id: int, provider: str, session_key: str,
    vodum_user_id: Optional[int], external_user_id: str, action: str, reason: str,
    account_username: Optional[str] = None, ips_json: Optional[str] = None,
    details_json: Optional[str] = None,
):
    db.execute("""
        INSERT INTO stream_enforcements(
            policy_id, server_id, provider, session_key, vodum_user_id,
            external_user_id, action, reason, account_username, ips_json, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        policy_id, server_id, provider, session_key, vodum_user_id,
        external_user_id, action, reason, account_username, ips_json, details_json,
    ))


def upsert_state(
    db, policy_id: int, server_id: int, vodum_user_id: Optional[int],
    external_user_id: str, warned: bool = False, killed: bool = False,
    reason: str = "",
):
    key = actor_key(vodum_user_id, external_user_id)
    row = db.query_one("""
        SELECT id FROM stream_enforcement_state
        WHERE policy_id=? AND server_id=? AND actor_key=? LIMIT 1
    """, (policy_id, server_id, key))
    if row:
        assignments = ["last_seen_at=CURRENT_TIMESTAMP", "last_reason=?"]
        params = [reason]
        if warned:
            assignments.append("warned_at=CURRENT_TIMESTAMP")
        if killed:
            assignments.append("killed_at=CURRENT_TIMESTAMP")
        db.execute(
            f"UPDATE stream_enforcement_state SET {', '.join(assignments)} WHERE id=?",
            (*params, row["id"]),
        )
        return
    db.execute("""
        INSERT INTO stream_enforcement_state(
            policy_id, server_id, actor_key, vodum_user_id, external_user_id,
            warned_at, killed_at, last_reason
        ) VALUES (
            ?, ?, ?, ?, ?,
            CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END,
            CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END, ?
        )
    """, (
        policy_id, server_id, key, vodum_user_id, external_user_id,
        1 if warned else 0, 1 if killed else 0, reason,
    ))


def already_warned_recently(
    db, policy_id: int, server_id: int, vodum_user_id: Optional[int],
    external_user_id: str, minutes: int = 5,
) -> bool:
    row = db.query_one("""
        SELECT 1 FROM stream_enforcement_state
        WHERE policy_id=? AND server_id=? AND actor_key=?
          AND warned_at IS NOT NULL
          AND datetime(warned_at) >= datetime('now', ?) LIMIT 1
    """, (
        policy_id, server_id, actor_key(vodum_user_id, external_user_id),
        f"-{int(minutes)} minutes",
    ))
    return bool(row)
