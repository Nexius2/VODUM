import json

from core.media_jobs import insert_plex_media_job
from core.user_sync_jobs import (
    get_preferred_plex_media_user_id,
    queue_plex_share_settings_sync,
)
from secret_store import find_plex_server_ids_by_token
from tasks_engine import enable_and_run_task_by_name


REPLICATED_PLEX_SHARE_KEYS = (
    "allowSync", "allowCameraUpload", "allowChannels",
    "filterMovies", "filterTelevision", "filterMusic",
)
TRUTHY_FORM_VALUES = {"1", "true", "on", "yes"}
PLEX_SHARE_FILTER_FIELDS = {"filterMovies", "filterTelevision", "filterMusic"}
PLEX_SHARE_TOGGLE_FIELDS = {"allowSync", "allowCameraUpload", "allowChannels"}


def update_single_plex_share_option(
    db,
    *,
    vodum_user_id: int,
    server_id: int,
    media_user_id: int,
    field: str,
    value,
    option_type: str,
    wake_task=enable_and_run_task_by_name,
) -> dict:
    allowed_fields = (
        PLEX_SHARE_FILTER_FIELDS
        if option_type == "filter"
        else PLEX_SHARE_TOGGLE_FIELDS
        if option_type == "toggle"
        else set()
    )
    if field not in allowed_fields:
        return {"ok": False, "reason": "invalid_field"}

    media_user = db.query_one(
        """
        SELECT mu.id, mu.details_json
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.id = ?
          AND mu.vodum_user_id = ?
          AND mu.server_id = ?
          AND s.type = 'plex'
          AND mu.type = 'plex'
        """,
        (media_user_id, vodum_user_id, server_id),
    )
    if not media_user:
        return {"ok": False, "reason": "media_user_not_found"}

    try:
        details = json.loads(media_user["details_json"] or "{}")
    except (TypeError, ValueError):
        details = {}
    if not isinstance(details, dict):
        details = {}
    plex_share = details.get("plex_share") or {}
    if not isinstance(plex_share, dict):
        plex_share = {}

    if option_type == "toggle":
        value = 1 if str(value).strip().lower() in TRUTHY_FORM_VALUES else 0
    else:
        value = str(value or "").strip()
    plex_share[field] = value
    details["plex_share"] = plex_share
    db.execute(
        "UPDATE media_users SET details_json = ? WHERE id = ?",
        (json.dumps(details, ensure_ascii=False), int(media_user["id"])),
    )
    queue_plex_share_settings_sync(
        db,
        user_id=vodum_user_id,
        server_id=server_id,
        reason=(
            f"plex_share_filter_{field}"
            if option_type == "filter"
            else f"plex_share_option_{field}"
        ),
        wake_task=wake_task,
    )
    return {"ok": True, "value": value}


def queue_user_plex_option_syncs(db, vodum_user_id: int, *, task_logger) -> int:
    media_users = db.query(
        """
        SELECT mu.id, mu.server_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'plex'
          AND mu.type = 'plex'
        """,
        (vodum_user_id,),
    )
    server_ids = sorted({
        int(media_user["server_id"])
        for media_user in media_users
        if media_user["server_id"] is not None
    })
    inserted_count = 0
    for server_id in server_ids:
        preferred_media_user_id = get_preferred_plex_media_user_id(
            db,
            vodum_user_id,
            server_id,
        )
        inserted = insert_plex_media_job(
            db,
            action="sync",
            vodum_user_id=vodum_user_id,
            server_id=server_id,
            library_id=None,
            dedupe_key=(
                f"plex:sync:server={server_id}:vodum_user={vodum_user_id}:"
                "user_detail_save"
            ),
            payload={
                "reason": "user_detail_save",
                "updated_options": True,
                "preferred_media_user_id": preferred_media_user_id,
            },
        )
        if inserted:
            inserted_count += 1
            task_logger.info(
                "[MEDIA JOB CREATED] provider=plex action=sync "
                "user_id=%s server_id=%s preferred_media_user_id=%s "
                "reason=user_detail_save",
                vodum_user_id,
                server_id,
                preferred_media_user_id,
            )
    try:
        enable_and_run_task_by_name("apply_plex_access_updates")
    except Exception:
        task_logger.exception(
            "User detail saved and Plex jobs persisted but worker startup failed | user_id=%s",
            vodum_user_id,
        )
    return inserted_count


def apply_user_plex_options(
    db,
    vodum_user_id: int,
    form,
    *,
    debug_logger=None,
) -> bool:
    media_users = db.query(
        """
        SELECT mu.id, mu.details_json
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'plex'
          AND mu.type = 'plex'
        """,
        (vodum_user_id,),
    )
    changed = False
    for media_user in media_users:
        media_user_id = int(media_user["id"])
        try:
            details = json.loads(media_user["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}
        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}
        old_plex_share = dict(plex_share)

        for form_prefix, share_key in (
            ("allow_sync", "allowSync"),
            ("allow_camera_upload", "allowCameraUpload"),
            ("allow_channels", "allowChannels"),
        ):
            values = form.getlist(f"{form_prefix}_{media_user_id}")
            if debug_logger is not None:
                debug_logger.debug(
                    "FORM DEBUG mu_id=%s %s getlist=%s",
                    media_user_id,
                    form_prefix,
                    values,
                )
            value = values[-1] if values else None
            plex_share[share_key] = (
                1 if str(value).strip().lower() in TRUTHY_FORM_VALUES else 0
                if value is not None
                else int(plex_share.get(share_key, 0) or 0)
            )

        plex_share["filterMovies"] = (form.get(f"filter_movies_{media_user_id}") or "").strip()
        plex_share["filterTelevision"] = (form.get(f"filter_television_{media_user_id}") or "").strip()
        plex_share["filterMusic"] = (form.get(f"filter_music_{media_user_id}") or "").strip()
        details["plex_share"] = plex_share

        if old_plex_share == plex_share:
            continue
        changed = True
        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), media_user_id),
        )
        replicate_plex_flags_same_owner(
            db,
            vodum_user_id=vodum_user_id,
            changed_media_user_id=media_user_id,
            plex_share_new=plex_share,
        )
    return changed


def replicate_plex_flags_same_owner(
    db,
    vodum_user_id: int,
    changed_media_user_id: int,
    plex_share_new: dict,
) -> int:
    row = db.query_one("SELECT server_id FROM media_users WHERE id = ?", (changed_media_user_id,))
    if not row:
        return 0
    server = db.query_one("SELECT token FROM servers WHERE id = ?", (int(row["server_id"]),))
    if not server:
        return 0
    owner_token = dict(server).get("token")
    if not owner_token:
        return 0

    owner_server_ids = find_plex_server_ids_by_token(db, owner_token)
    if not owner_server_ids:
        return 0
    placeholders = ",".join(["?"] * len(owner_server_ids))
    rows = db.query(
        f"""
        SELECT mu.id, mu.details_json
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'plex'
          AND mu.type = 'plex'
          AND mu.server_id IN ({placeholders})
        """,
        (vodum_user_id, *owner_server_ids),
    )

    updated = 0
    for media_user in rows:
        try:
            details = json.loads(media_user["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}
        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}
        for key in REPLICATED_PLEX_SHARE_KEYS:
            if key in plex_share_new:
                plex_share[key] = plex_share_new[key]
        details["plex_share"] = plex_share
        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(media_user["id"])),
        )
        updated += 1
    return updated
