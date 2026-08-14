import json
from datetime import datetime, timezone

from core.migrations.execution import refresh_campaign_status
from core.migrations.phase3 import (
    remove_validated_source_access,
    rollback_destination_access,
    rollback_source_access,
)


def request_invitation_reconciliation(db, campaign_id: int, *, wake_task) -> dict:
    campaign = db.query_one(
        "SELECT id, status FROM migration_campaigns WHERE id = ?",
        (campaign_id,),
    )
    if not campaign:
        return {"ok": False, "reason": "migration_campaign_not_found"}
    db.execute(
        """
        UPDATE migration_users
        SET updated_at=datetime('now','-11 minutes')
        WHERE campaign_id=? AND status='waiting_acceptance'
        """,
        (campaign_id,),
    )
    wake_task("migration_worker")
    return {"ok": True}


def validate_migration_destination(db, campaign_id: int, migration_user_id: int) -> dict:
    row = db.query_one(
        "SELECT status, result_json FROM migration_users WHERE id = ? AND campaign_id = ?",
        (migration_user_id, campaign_id),
    )
    if not row or row["status"] != "waiting_validation":
        return {"ok": False, "reason": "migration_validation_not_available"}
    try:
        result = json.loads(row["result_json"] or "{}")
    except (TypeError, ValueError):
        result = {}
    if not isinstance(result, dict):
        result = {}
    result["destination_validated_at"] = result.get(
        "destination_validated_at"
    ) or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    result["destination_validation_method"] = result.get(
        "destination_validation_method"
    ) or "manual"
    db.execute(
        """
        UPDATE migration_users
        SET status='completed', result_json=?,
            completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP),
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (json.dumps(result), migration_user_id),
    )
    refresh_campaign_status(db, campaign_id)
    return {"ok": True}


def run_migration_access_operation(
    db,
    campaign_id: int,
    *,
    confirmation: str,
    operation: str,
    wake_task,
) -> dict:
    campaign_row = db.query_one(
        """
        SELECT id, name, source_server_id, destination_server_id, intent
        FROM migration_campaigns WHERE id = ?
        """,
        (campaign_id,),
    )
    if not campaign_row:
        return {"ok": False, "reason": "migration_campaign_not_found"}
    campaign = dict(campaign_row)
    if str(confirmation or "").strip() != str(campaign.get("name") or "").strip():
        return {"ok": False, "reason": "migration_confirmation_mismatch"}
    if operation == "remove_source" and campaign.get("intent") == "copy":
        return {"ok": False, "reason": "migration_copy_has_no_source_removal"}

    operations = {
        "remove_source": (
            remove_validated_source_access,
            "source_server_id",
            "migration_source_removal_requested",
        ),
        "rollback_source": (
            rollback_source_access,
            "source_server_id",
            "migration_source_rollback_requested",
        ),
        "rollback_destination": (
            rollback_destination_access,
            "destination_server_id",
            "migration_destination_rollback_requested",
        ),
    }
    selected = operations.get(operation)
    if not selected:
        raise ValueError(f"Unsupported migration access operation: {operation}")
    handler, server_key, success_message = selected
    try:
        result = handler(db, campaign_id)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "exception": exc}

    server = db.query_one(
        "SELECT type FROM servers WHERE id = ?",
        (campaign[server_key],),
    )
    if result.get("queued") and server:
        provider_task = (
            "apply_plex_access_updates"
            if server["type"] == "plex"
            else "apply_jellyfin_access_updates"
        )
        wake_task(provider_task)
        wake_task("migration_worker")
    return {
        "ok": True,
        "message": success_message,
        "result": result,
        "operation": operation,
    }
