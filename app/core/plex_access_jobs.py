from __future__ import annotations

import json

from core.plex_access_identity import row_get
from logging_utils import get_logger


logger = get_logger("plex_access_jobs")


def cleanup_old_jobs(db):
    deleted = db.execute(
        """
        DELETE FROM media_jobs
        WHERE provider = 'plex'
          AND action IN ('grant','revoke','sync')
          AND success = 1
          AND executed_at IS NOT NULL
          AND executed_at < datetime('now', '-7 days')
        """
    ).rowcount
    logger.info("Jobs cleanup: %s successful Plex job(s) deleted", deleted)


def job_payload_as_dict(job):
    raw = row_get(job, "payload_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_media_user(db, vodum_user_id: int, server_id: int, job=None):
    payload = job_payload_as_dict(job)
    preferred_media_user_id = (
        payload.get("preferred_media_user_id") or payload.get("media_user_id")
    )
    if preferred_media_user_id is not None:
        try:
            preferred_media_user_id = int(preferred_media_user_id)
        except Exception:
            preferred_media_user_id = None

    columns = (
        "id, server_id, vodum_user_id, external_user_id, username, email, "
        "avatar, stored_password, type, role, joined_at, accepted_at, "
        "raw_json, details_json"
    )
    if preferred_media_user_id:
        row = db.query_one(
            f"""
            SELECT {columns} FROM media_users
            WHERE id = ? AND server_id = ?
            """,
            (preferred_media_user_id, server_id),
        )
        if row:
            return row
    if vodum_user_id is None:
        raise RuntimeError("Invalid job: vodum_user_id is NULL")

    rows = db.query(
        f"""
        SELECT {columns} FROM media_users
        WHERE vodum_user_id = ? AND server_id = ?
        ORDER BY
            CASE WHEN LOWER(COALESCE(role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(role, '')) = 'unfriended' THEN 1 ELSE 0 END ASC,
            id ASC
        """,
        (vodum_user_id, server_id),
    )
    if not rows:
        raise RuntimeError(
            f"No media_user found for vodum_user_id={vodum_user_id} "
            f"on server_id={server_id}"
        )
    if len(rows) > 1:
        logger.warning(
            "[MEDIA USER DUPLICATE] vodum_user_id=%s server_id=%s rows=%s",
            vodum_user_id,
            server_id,
            [row_get(row, "id") for row in rows],
        )
    return rows[0]


def is_owner_media_user(user_row) -> bool:
    try:
        return (user_row["role"] or "").strip().lower() == "owner"
    except Exception:
        return False


def parse_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default


def get_plex_share_settings_from_user(user_row):
    defaults = (False, False, False, "", "", "")
    if not user_row:
        return defaults
    raw = row_get(user_row, "details_json")
    if not raw:
        return defaults
    try:
        details = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        details = {}
    if not isinstance(details, dict):
        details = {}
    share = details.get("plex_share") or {}
    if not isinstance(share, dict):
        share = {}
    result = (
        parse_bool(share.get("allowSync"), False),
        parse_bool(share.get("allowCameraUpload"), False),
        parse_bool(share.get("allowChannels"), False),
        str(share.get("filterMovies") or ""),
        str(share.get("filterTelevision") or ""),
        str(share.get("filterMusic") or ""),
    )
    logger.info(
        "[SETTINGS] allowSync=%s (%s) allowCameraUpload=%s (%s) "
        "allowChannels=%s (%s)",
        result[0],
        type(result[0]).__name__,
        result[1],
        type(result[1]).__name__,
        result[2],
        type(result[2]).__name__,
    )
    return result
