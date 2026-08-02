import json
from datetime import datetime


def build_migration_report(
    campaign,
    users: list[dict],
    *,
    generated_at: datetime | None = None,
) -> dict:
    safe_users = []
    status_counts = {}
    summary = {
        "users": len(users),
        "statuses": status_counts,
        "validated": 0,
        "source_removal_requested": 0,
        "source_removed": 0,
        "source_restored": 0,
        "destination_rollback_requested": 0,
        "destination_rolled_back": 0,
        "provider_job_errors": 0,
    }
    for row in users:
        user = dict(row)
        try:
            result = json.loads(user.get("result_json") or "{}")
        except Exception:
            result = {}
        result.pop("encrypted_generated_password", None)
        user["result"] = result
        user.pop("result_json", None)
        safe_users.append(user)

        status = user["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        summary["validated"] += int(bool(result.get("destination_validated_at")))
        summary["source_removal_requested"] += int(bool(result.get("source_removal_requested_at")))
        summary["source_removed"] += int(bool(result.get("source_removed_at")))
        summary["source_restored"] += int(bool(result.get("source_restored_at")))
        summary["destination_rollback_requested"] += int(
            bool(result.get("destination_rollback_requested_at"))
        )
        summary["destination_rolled_back"] += int(bool(result.get("destination_rolled_back_at")))
        summary["provider_job_errors"] += int(bool(
            result.get("source_removal_job_error")
            or result.get("source_restoration_job_error")
            or result.get("destination_rollback_job_error")
        ))

    return {
        "ok": True,
        "generated_at": (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S"),
        "campaign": dict(campaign),
        "summary": summary,
        "users": safe_users,
    }
