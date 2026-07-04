"""Explicit source-access removal and rollback for validated migrations."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.media_jobs import insert_jellyfin_media_job, insert_plex_media_job
from core.migrations.analysis import is_server_online


def _json_dict(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_timestamp(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    return None


def _current_source_access(db, source_server_id: int, vodum_user_id: int) -> dict[str, list[int]]:
    rows = db.query(
        """
        SELECT mu.id AS media_user_id, mul.library_id
        FROM media_users mu
        JOIN media_user_libraries mul ON mul.media_user_id=mu.id
        JOIN libraries l ON l.id=mul.library_id AND l.server_id=?
        WHERE mu.server_id=? AND mu.vodum_user_id=?
        ORDER BY mu.id, mul.library_id
        """,
        (source_server_id, source_server_id, vodum_user_id),
    )
    access: dict[str, list[int]] = {}
    for row in rows:
        access.setdefault(str(row["media_user_id"]), []).append(int(row["library_id"]))
    return access


def _queue_access_sync(
    db,
    *,
    provider: str,
    action: str,
    campaign_id: int,
    migration_user_id: int,
    vodum_user_id: int,
    server_id: int,
    scope: str,
) -> tuple[bool, str]:
    dedupe_key = f"migration:{campaign_id}:{scope}:{action}:server={server_id}:user={vodum_user_id}"
    kwargs = {
        "db": db,
        "action": action,
        "vodum_user_id": vodum_user_id,
        "server_id": server_id,
        "library_id": None,
        "dedupe_key": dedupe_key,
        "payload": {
            "reason": "migration_phase3",
            "campaign_id": campaign_id,
            "migration_user_id": migration_user_id,
            "operation": action,
            "scope": scope,
        },
        "cancel_reason": f"Canceled because a newer migration {scope} access operation was queued",
    }
    if provider == "plex":
        return insert_plex_media_job(**kwargs), dedupe_key
    return insert_jellyfin_media_job(**kwargs), dedupe_key


def _queue_source_sync(db, *, provider: str, action: str, campaign_id: int, migration_user_id: int, vodum_user_id: int, server_id: int) -> tuple[bool, str]:
    return _queue_access_sync(
        db,
        provider=provider,
        action=action,
        campaign_id=campaign_id,
        migration_user_id=migration_user_id,
        vodum_user_id=vodum_user_id,
        server_id=server_id,
        scope="source",
    )


def _queue_destination_sync(db, *, provider: str, action: str, campaign_id: int, migration_user_id: int, vodum_user_id: int, server_id: int) -> tuple[bool, str]:
    return _queue_access_sync(
        db,
        provider=provider,
        action=action,
        campaign_id=campaign_id,
        migration_user_id=migration_user_id,
        vodum_user_id=vodum_user_id,
        server_id=server_id,
        scope="destination",
    )


def _campaign_options(campaign: dict) -> dict:
    return _json_dict(campaign.get("options_json"))


def _removal_available_at(result: dict, safety_delay_days: int) -> datetime | None:
    validated_at = str(result.get("destination_validated_at") or "").strip()
    if not validated_at:
        return None
    validated = _parse_timestamp(validated_at)
    if not validated:
        return None
    return validated + timedelta(days=max(0, safety_delay_days))


def reconcile_destination_usage(db) -> int:
    """Validate waiting destinations after their first observed media activity."""
    validated = 0
    try:
        rows = db.query(
            """
            SELECT mu.id, mu.destination_media_user_id, mu.result_json
            FROM migration_users mu
            WHERE mu.status='waiting_validation' AND mu.destination_media_user_id IS NOT NULL
            """
        )
    except Exception:
        return 0
    for raw in rows:
        user = dict(raw)
        result = _json_dict(user.get("result_json"))
        since = str(result.get("destination_created_at") or "").strip()
        if not since:
            continue
        try:
            activity = db.query_one(
                """
                SELECT MAX(activity_at) AS activity_at FROM (
                  SELECT MAX(last_seen_at) AS activity_at FROM media_sessions WHERE media_user_id=?
                  UNION ALL
                  SELECT MAX(ts) AS activity_at FROM media_events WHERE media_user_id=?
                )
                WHERE datetime(activity_at) >= datetime(?)
                """,
                (user["destination_media_user_id"], user["destination_media_user_id"], since),
            )
        except Exception:
            continue
        if not activity or not activity["activity_at"]:
            continue
        result["destination_validated_at"] = str(activity["activity_at"])
        result["destination_validation_method"] = "first_activity"
        db.execute(
            """
            UPDATE migration_users
            SET status='completed', result_json=?, completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP),
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (json.dumps(result), user["id"]),
        )
        validated += 1
    return validated


def reconcile_source_jobs(db) -> int:
    """Copy provider job outcomes into migration audit data."""
    updated = 0
    try:
        rows = db.query(
            """
            SELECT id,result_json FROM migration_users
            WHERE result_json LIKE '%source_%_job_key%'
               OR result_json LIKE '%destination_%_job_key%'
            """
        )
    except Exception:
        return 0
    operations = {
        "source": ("removal", "restoration"),
        "destination": ("rollback",),
    }
    for raw in rows:
        user = dict(raw)
        result = _json_dict(user.get("result_json"))
        changed = False
        for scope, scope_operations in operations.items():
            for operation in scope_operations:
                key = result.get(f"{scope}_{operation}_job_key")
                if not key:
                    continue
                job = db.query_one(
                    "SELECT status,last_error,processed_at FROM media_jobs WHERE dedupe_key=? ORDER BY id DESC LIMIT 1",
                    (key,),
                )
                if not job:
                    continue
                status = str(job["status"] or "")
                if result.get(f"{scope}_{operation}_job_status") != status:
                    result[f"{scope}_{operation}_job_status"] = status
                    if job["last_error"]:
                        result[f"{scope}_{operation}_job_error"] = str(job["last_error"])
                    if status == "success":
                        result[f"{scope}_{operation}_applied_at"] = str(job["processed_at"] or _utc_now())
                        if scope == "source" and operation == "removal":
                            result["source_removed_at"] = result[f"{scope}_{operation}_applied_at"]
                        elif scope == "source" and operation == "restoration":
                            result["source_restored_at"] = result[f"{scope}_{operation}_applied_at"]
                            result.pop("source_removed_at", None)
                        elif scope == "destination" and operation == "rollback":
                            result["destination_rolled_back_at"] = result[f"{scope}_{operation}_applied_at"]
                    changed = True
        if changed:
            db.execute(
                "UPDATE migration_users SET result_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(result), user["id"]),
            )
            updated += 1
    return updated


def remove_validated_source_access(db, campaign_id: int) -> dict:
    campaign = dict(db.query_one("SELECT id, name, source_server_id, destination_server_id, migration_type, migration_mode, intent, status, options_json, library_mapping_json, analysis_json, scheduled_at, batch_size, created_at, updated_at, started_at, completed_at FROM migration_campaigns WHERE id=?", (campaign_id,)) or {})
    if not campaign:
        raise ValueError("Migration campaign not found.")
    if str(campaign.get("intent") or "copy").lower() == "copy":
        raise ValueError("Copy migrations can never remove source access.")
    source = dict(db.query_one("SELECT id, type, status FROM servers WHERE id=?", (campaign["source_server_id"],)) or {})
    if not source:
        raise ValueError("Source server not found.")
    if not is_server_online(source.get("status")):
        raise ValueError("Source server must be online.")
    safety_delay_days = max(0, int(_campaign_options(campaign).get("safety_delay_days", 7)))

    rows = db.query(
        """
        SELECT id, campaign_id, vodum_user_id, source_media_user_id, destination_media_user_id, status, eligibility, blockers_json, options_json, source_snapshot_json, result_json, attempts, last_error, created_at, updated_at, started_at, completed_at FROM migration_users
        WHERE campaign_id=? AND status='completed'
        ORDER BY id
        """,
        (campaign_id,),
    )
    removed = queued = skipped = 0
    for raw in rows:
        user = dict(raw)
        result = _json_dict(user.get("result_json"))
        if not result.get("destination_validated_at") or result.get("source_removed_at"):
            skipped += 1
            continue
        if (
            result.get("source_removal_requested_at")
            and str(result.get("source_removal_job_status") or "") in {"queued", "running", "success"}
        ):
            skipped += 1
            continue
        available_at = _removal_available_at(result, safety_delay_days)
        if not available_at or datetime.utcnow() < available_at:
            skipped += 1
            continue
        snapshot = _json_dict(user.get("source_snapshot_json"))
        source_access = snapshot.get("source_access") or _current_source_access(
            db, int(source["id"]), int(user["vodum_user_id"])
        )
        snapshot["source_access"] = source_access
        db.execute(
            """
            DELETE FROM media_user_libraries
            WHERE media_user_id IN (
              SELECT id FROM media_users WHERE server_id=? AND vodum_user_id=?
            )
            AND library_id IN (SELECT id FROM libraries WHERE server_id=?)
            """,
            (source["id"], user["vodum_user_id"], source["id"]),
        )
        inserted, job_key = _queue_source_sync(
            db,
            provider=str(source["type"]).lower(),
            action="revoke" if str(source["type"]).lower() == "plex" else "sync",
            campaign_id=campaign_id,
            migration_user_id=int(user["id"]),
            vodum_user_id=int(user["vodum_user_id"]),
            server_id=int(source["id"]),
        )
        queued += int(inserted)
        result["source_removal_requested_at"] = result.get("source_removal_requested_at") or _utc_now()
        result["source_removal_job_key"] = job_key
        result["source_removal_job_status"] = "queued"
        result.pop("source_restored_at", None)
        db.execute(
            "UPDATE migration_users SET source_snapshot_json=?, result_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(snapshot), json.dumps(result), user["id"]),
        )
        removed += 1
    return {"removed": removed, "queued": queued, "skipped": skipped}


def _current_destination_library_ids(db, media_user_id: int, destination_server_id: int) -> list[int]:
    rows = db.query(
        """
        SELECT mul.library_id
        FROM media_user_libraries mul
        JOIN libraries l ON l.id=mul.library_id AND l.server_id=?
        WHERE mul.media_user_id=?
        ORDER BY mul.library_id
        """,
        (int(destination_server_id), int(media_user_id)),
    )
    return [int(row["library_id"]) for row in rows]


def rollback_destination_access(db, campaign_id: int) -> dict:
    campaign = dict(db.query_one("SELECT id, name, source_server_id, destination_server_id, migration_type, migration_mode, intent, status, options_json, library_mapping_json, analysis_json, scheduled_at, batch_size, created_at, updated_at, started_at, completed_at FROM migration_campaigns WHERE id=?", (campaign_id,)) or {})
    if not campaign:
        raise ValueError("Migration campaign not found.")
    destination = dict(db.query_one("SELECT id, type, status FROM servers WHERE id=?", (campaign["destination_server_id"],)) or {})
    if not destination:
        raise ValueError("Destination server not found.")
    if not is_server_online(destination.get("status")):
        raise ValueError("Destination server must be online.")

    rolled_back = queued = skipped = 0
    for raw in db.query("SELECT id, campaign_id, vodum_user_id, source_media_user_id, destination_media_user_id, status, eligibility, blockers_json, options_json, source_snapshot_json, result_json, attempts, last_error, created_at, updated_at, started_at, completed_at FROM migration_users WHERE campaign_id=? ORDER BY id", (campaign_id,)):
        user = dict(raw)
        result = _json_dict(user.get("result_json"))
        media_user_id = result.get("destination_media_user_id") or user.get("destination_media_user_id")
        if not media_user_id or result.get("destination_rolled_back_at"):
            skipped += 1
            continue
        if (
            result.get("destination_rollback_requested_at")
            and str(result.get("destination_rollback_job_status") or "") in {"queued", "running", "success"}
        ):
            skipped += 1
            continue
        added_library_ids = {
            int(library_id)
            for library_id in result.get("destination_library_ids_added", [])
            if str(library_id).isdigit()
        }
        if not added_library_ids:
            skipped += 1
            continue
        current_library_ids = set(_current_destination_library_ids(db, int(media_user_id), int(destination["id"])))
        removable_library_ids = sorted(added_library_ids & current_library_ids)
        if not removable_library_ids:
            skipped += 1
            continue
        placeholders = ",".join("?" for _ in removable_library_ids)
        db.execute(
            f"DELETE FROM media_user_libraries WHERE media_user_id=? AND library_id IN ({placeholders})",
            (int(media_user_id), *removable_library_ids),
        )
        remaining_library_ids = _current_destination_library_ids(db, int(media_user_id), int(destination["id"]))
        action = "revoke" if str(destination["type"]).lower() == "plex" and not remaining_library_ids else "sync"
        inserted, job_key = _queue_destination_sync(
            db,
            provider=str(destination["type"]).lower(),
            action=action,
            campaign_id=campaign_id,
            migration_user_id=int(user["id"]),
            vodum_user_id=int(user["vodum_user_id"]),
            server_id=int(destination["id"]),
        )
        queued += int(inserted)
        result["destination_rollback_requested_at"] = result.get("destination_rollback_requested_at") or _utc_now()
        result["destination_rollback_job_key"] = job_key
        result["destination_rollback_job_status"] = "queued"
        result["destination_rollback_removed_library_ids"] = removable_library_ids
        result["destination_rollback_action"] = action
        db.execute(
            "UPDATE migration_users SET result_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(result), user["id"]),
        )
        rolled_back += 1
    return {"rolled_back": rolled_back, "queued": queued, "skipped": skipped}


def rollback_source_access(db, campaign_id: int) -> dict:
    campaign = dict(db.query_one("SELECT id, name, source_server_id, destination_server_id, migration_type, migration_mode, intent, status, options_json, library_mapping_json, analysis_json, scheduled_at, batch_size, created_at, updated_at, started_at, completed_at FROM migration_campaigns WHERE id=?", (campaign_id,)) or {})
    if not campaign:
        raise ValueError("Migration campaign not found.")
    source = dict(db.query_one("SELECT id, type, status FROM servers WHERE id=?", (campaign["source_server_id"],)) or {})
    if not source:
        raise ValueError("Source server not found.")
    if not is_server_online(source.get("status")):
        raise ValueError("Source server must be online.")
    restored = queued = skipped = 0
    for raw in db.query("SELECT id, campaign_id, vodum_user_id, source_media_user_id, destination_media_user_id, status, eligibility, blockers_json, options_json, source_snapshot_json, result_json, attempts, last_error, created_at, updated_at, started_at, completed_at FROM migration_users WHERE campaign_id=? ORDER BY id", (campaign_id,)):
        user = dict(raw)
        result = _json_dict(user.get("result_json"))
        snapshot = _json_dict(user.get("source_snapshot_json"))
        source_access = snapshot.get("source_access") or {}
        if not (result.get("source_removed_at") or result.get("source_removal_requested_at")) or not source_access:
            skipped += 1
            continue
        for media_user_id, library_ids in source_access.items():
            for library_id in library_ids:
                db.execute(
                    "INSERT OR IGNORE INTO media_user_libraries(media_user_id,library_id) VALUES(?,?)",
                    (int(media_user_id), int(library_id)),
                )
        inserted, job_key = _queue_source_sync(
            db,
            provider=str(source["type"]).lower(),
            action="sync",
            campaign_id=campaign_id,
            migration_user_id=int(user["id"]),
            vodum_user_id=int(user["vodum_user_id"]),
            server_id=int(source["id"]),
        )
        queued += int(inserted)
        result["source_restoration_requested_at"] = _utc_now()
        result["source_restoration_job_key"] = job_key
        result["source_restoration_job_status"] = "queued"
        db.execute(
            "UPDATE migration_users SET result_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(result), user["id"]),
        )
        restored += 1
    return {"restored": restored, "queued": queued, "skipped": skipped}
