import json
from datetime import datetime, timedelta

from core.migrations.analysis import SUPPORTED_PROVIDERS, is_server_online


MIGRATION_USER_DETAIL_COLUMNS = """
              mu.id,
              mu.campaign_id,
              mu.vodum_user_id,
              mu.source_media_user_id,
              mu.destination_media_user_id,
              mu.status,
              mu.eligibility,
              mu.blockers_json,
              mu.options_json,
              mu.source_snapshot_json,
              mu.result_json,
              mu.attempts,
              mu.last_error,
              mu.created_at,
              mu.updated_at,
              mu.started_at,
              mu.completed_at
"""

MIGRATION_LIBRARY_MAPPING_COLUMNS = """
              mlm.id,
              mlm.campaign_id,
              mlm.source_library_id,
              mlm.destination_library_id,
              mlm.mapping_status,
              mlm.created_at,
              mlm.updated_at
"""


def load_campaign_detail_relations(
    db,
    campaign_id: int,
    destination_server_id: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    users = [
        dict(row)
        for row in db.query(
            f"""
            SELECT
{MIGRATION_USER_DETAIL_COLUMNS}, vu.username, vu.email, vu.status AS vodum_status
            FROM migration_users mu
            JOIN vodum_users vu ON vu.id = mu.vodum_user_id
            WHERE mu.campaign_id = ?
            ORDER BY
              CASE mu.eligibility
                WHEN 'blocked' THEN 0
                WHEN 'ready' THEN 1
                ELSE 2
              END,
              lower(COALESCE(vu.username, '')),
              mu.id
            """,
            (campaign_id,),
        )
    ]
    mappings = [
        dict(row)
        for row in db.query(
            f"""
            SELECT
{MIGRATION_LIBRARY_MAPPING_COLUMNS},
              source.name AS source_name,
              source.type AS source_type,
              destination.name AS destination_name,
              destination.type AS destination_type
            FROM migration_library_mappings mlm
            JOIN libraries source ON source.id = mlm.source_library_id
            LEFT JOIN libraries destination ON destination.id = mlm.destination_library_id
            WHERE mlm.campaign_id = ?
            ORDER BY lower(source.name), mlm.id
            """,
            (campaign_id,),
        )
    ]
    destination_libraries = [
        dict(row)
        for row in db.query(
            "SELECT id,name,type,section_id FROM libraries WHERE server_id=? ORDER BY lower(name),id",
            (destination_server_id,),
        )
    ]
    return users, group_mapping_rows(mappings), destination_libraries


def normalize_campaign_detail(campaign_row) -> dict:
    campaign = dict(campaign_row)
    try:
        options = json.loads(campaign.get("options_json") or "{}")
    except Exception:
        options = {}
    campaign["safety_delay_days"] = max(0, int(options.get("safety_delay_days", 7)))
    campaign["jellyfin_password_strategy"] = str(
        options.get("jellyfin_password_strategy") or "generated"
    )
    campaign["jellyfin_temp_password_configured"] = bool(
        options.get("jellyfin_temp_password")
    )
    campaign["jellyfin_auto_deliver_credentials"] = bool(
        options.get("jellyfin_auto_deliver_credentials")
    )
    scheduled_raw = str(campaign.get("scheduled_at") or "")
    campaign["scheduled_at_input"] = (
        f"{scheduled_raw[:10]}T{scheduled_raw[11:16]}"
        if len(scheduled_raw) >= 16 and scheduled_raw[10:11] == " "
        else scheduled_raw[:16]
    )
    return campaign


def paginate_campaign_users(
    users: list[dict],
    *,
    requested_page: int,
    requested_per_page: int,
) -> tuple[list[dict], int, int, int, int]:
    per_page = requested_per_page if requested_per_page in (20, 50, 100) else 20
    total = len(users)
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(max(requested_page, 1), total_pages)
    offset = (page - 1) * per_page
    return users[offset:offset + per_page], page, per_page, total, total_pages


def enrich_campaign_users(
    users: list[dict],
    mapping_groups: list[dict],
    *,
    safety_delay_days: int,
    now: datetime | None = None,
) -> dict:
    source_libraries_by_id = {
        int(group["source_library_id"]): group for group in mapping_groups
    }
    summary = {
        "total": len(users),
        "ready": sum(1 for user in users if user["eligibility"] == "ready"),
        "blocked": sum(1 for user in users if user["eligibility"] == "blocked"),
        "already_present": sum(1 for user in users if user["eligibility"] == "already_present"),
        "unmapped": sum(1 for mapping in mapping_groups if not mapping["destination_library_ids"]),
        "failed": sum(1 for user in users if user["status"] == "failed"),
        "excluded": sum(1 for user in users if user["status"] == "excluded"),
    }
    for user in users:
        try:
            user["blockers"] = json.loads(user.get("blockers_json") or "[]")
        except Exception:
            user["blockers"] = []
        try:
            result = json.loads(user.get("result_json") or "{}")
        except Exception:
            result = {}
        try:
            user_options = json.loads(user.get("options_json") or "{}")
        except Exception:
            user_options = {}
        try:
            source_snapshot = json.loads(user.get("source_snapshot_json") or "{}")
        except Exception:
            source_snapshot = {}
        source_library_ids = []
        for ids in (source_snapshot.get("source_access") or {}).values():
            for library_id in ids or []:
                try:
                    source_library_ids.append(int(library_id))
                except (TypeError, ValueError):
                    pass
        user["source_library_ids"] = sorted(set(source_library_ids))
        user["source_libraries"] = [
            source_libraries_by_id[library_id]
            for library_id in user["source_library_ids"]
            if library_id in source_libraries_by_id
        ]
        raw_user_overrides = user_options.get("library_mapping_overrides") or {}
        user["library_mapping_overrides"] = {}
        if isinstance(raw_user_overrides, dict):
            for source_id, destination_ids in raw_user_overrides.items():
                if not str(source_id).isdigit():
                    continue
                parsed_destinations = []
                for destination_id in destination_ids or []:
                    try:
                        parsed_destinations.append(int(destination_id))
                    except (TypeError, ValueError):
                        continue
                user["library_mapping_overrides"][int(source_id)] = sorted(set(parsed_destinations))
        user["has_credentials"] = bool(result.get("encrypted_generated_password"))
        for field in (
            "plex_invited_at", "plex_last_checked_at", "plex_accepted_at",
            "plex_last_reminder_at", "destination_validated_at",
            "destination_rollback_requested_at", "destination_rolled_back_at",
            "destination_rollback_job_status", "destination_rollback_job_error",
            "source_removed_at", "source_removal_requested_at", "source_restored_at",
            "source_restoration_requested_at", "source_removal_job_status",
            "source_removal_job_error", "source_restoration_job_status",
            "source_restoration_job_error", "destination_validation_method",
            "credentials_delivery_queued_at", "credentials_delivery_template_id",
            "credentials_delivery_skipped_reason",
        ):
            user[field] = result.get(field)
        user["plex_reminder_count"] = int(result.get("plex_reminder_count") or 0)
        user["destination_library_ids_added"] = [
            int(library_id)
            for library_id in result.get("destination_library_ids_added", [])
            if str(library_id).isdigit()
        ]
        user["source_removal_available_at"] = None
        if user["destination_validated_at"]:
            try:
                user["source_removal_available_at"] = (
                    datetime.strptime(user["destination_validated_at"][:19], "%Y-%m-%d %H:%M:%S")
                    + timedelta(days=safety_delay_days)
                ).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

    summary["validated"] = sum(1 for user in users if user.get("destination_validated_at"))
    summary["destination_rollback_requested"] = sum(1 for user in users if user.get("destination_rollback_requested_at"))
    summary["destination_rolled_back"] = sum(1 for user in users if user.get("destination_rolled_back_at"))
    summary["destination_rollback_available"] = sum(
        1 for user in users
        if user.get("destination_media_user_id")
        and user.get("destination_library_ids_added")
        and not user.get("destination_rollback_requested_at")
        and not user.get("destination_rolled_back_at")
    )
    summary["source_removed"] = sum(1 for user in users if user.get("source_removed_at"))
    summary["source_removal_requested"] = sum(1 for user in users if user.get("source_removal_requested_at"))
    current_timestamp = (now or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")
    summary["removal_ready"] = sum(
        1 for user in users
        if user.get("source_removal_available_at")
        and user["source_removal_available_at"] <= current_timestamp
        and not user.get("source_removed_at")
        and not (
            user.get("source_removal_requested_at")
            and user.get("source_removal_job_status") in ("queued", "running", "success")
        )
    )
    return summary


def migration_campaign_overview(db, *, schema_available: bool) -> tuple[dict, list[dict]]:
    counts = {
        "active": 0,
        "completed": 0,
        "needs_attention": 0,
        "waiting_users": 0,
        "blocked_users": 0,
    }
    if not schema_available:
        return counts, []

    status_rows = db.query(
        """
        SELECT status, COUNT(*) AS total
        FROM migration_campaigns
        GROUP BY status
        """
    )
    campaigns = [
        dict(row)
        for row in db.query(
            """
            SELECT
              mc.id, mc.name, mc.migration_type, mc.migration_mode,
              mc.status, mc.created_at,
              source.name AS source_name,
              destination.name AS destination_name,
              COUNT(DISTINCT mu.id) AS users_count
            FROM migration_campaigns mc
            JOIN servers source ON source.id = mc.source_server_id
            JOIN servers destination ON destination.id = mc.destination_server_id
            LEFT JOIN migration_users mu ON mu.campaign_id = mc.id
            GROUP BY mc.id
            ORDER BY mc.updated_at DESC, mc.id DESC
            LIMIT 20
            """
        )
    ]
    user_counts = db.query_one(
        """
        SELECT
          SUM(CASE WHEN status IN ('waiting_acceptance','waiting_validation') THEN 1 ELSE 0 END) AS waiting_users,
          SUM(CASE WHEN eligibility='blocked' THEN 1 ELSE 0 END) AS blocked_users
        FROM migration_users
        """
    )
    if user_counts:
        counts["waiting_users"] = int(user_counts["waiting_users"] or 0)
        counts["blocked_users"] = int(user_counts["blocked_users"] or 0)

    for row in status_rows:
        status = str(row["status"] or "")
        total = int(row["total"] or 0)
        if status == "completed":
            counts["completed"] += total
        elif status in ("needs_attention", "failed"):
            counts["needs_attention"] += total
        elif status in ("scheduled", "running", "paused", "waiting_users"):
            counts["active"] += total
    return counts, campaigns


def online_migration_servers(db) -> list[dict]:
    return [
        dict(row)
        for row in db.query(
            """
            SELECT id, name, type, status, last_checked
            FROM servers
            ORDER BY lower(name), id
            """
        )
        if str(row["type"] or "").strip().lower() in SUPPORTED_PROVIDERS
        and is_server_online(row["status"])
    ]


def mapping_overrides_from_form(form, prefix: str = "library_mapping_") -> dict[int, list[int]]:
    overrides: dict[int, list[int]] = {}
    for key in form.keys():
        if not key.startswith(prefix):
            continue
        try:
            source_library_id = int(key[len(prefix):])
        except (TypeError, ValueError):
            continue
        destination_ids = []
        for value in form.getlist(key):
            try:
                if str(value).strip():
                    destination_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        overrides[source_library_id] = sorted(set(destination_ids))
    return overrides


def group_mapping_rows(rows: list[dict]) -> list[dict]:
    groups: dict[int, dict] = {}
    for row in rows:
        source_id = int(row["source_library_id"])
        group = groups.setdefault(source_id, {
            "source_library_id": source_id,
            "source_name": row.get("source_name"),
            "source_type": row.get("source_type"),
            "mapping_status": row.get("mapping_status"),
            "destination_library_ids": [],
            "destinations": [],
        })
        if row.get("destination_library_id"):
            destination_id = int(row["destination_library_id"])
            if destination_id not in group["destination_library_ids"]:
                group["destination_library_ids"].append(destination_id)
                group["destinations"].append({
                    "id": destination_id,
                    "name": row.get("destination_name"),
                    "type": row.get("destination_type"),
                })
                group["mapping_status"] = "mapped"
    return list(groups.values())
