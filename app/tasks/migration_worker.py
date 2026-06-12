import json
from datetime import datetime

from logging_utils import get_logger
from tasks_engine import task_logs
from core.migrations.execution import process_migration_user, refresh_campaign_status
from core.migrations.phase3 import reconcile_destination_usage, reconcile_source_jobs


log = get_logger("migration_worker")


def _cleanup_expired_credentials(db) -> int:
    cleaned = 0
    try:
        rows = db.query(
            "SELECT id,result_json FROM migration_users WHERE result_json LIKE '%encrypted_generated_password%'"
        )
    except Exception:
        return 0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        try:
            result = json.loads(row["result_json"] or "{}")
        except Exception:
            continue
        expires_at = str(result.get("credentials_expires_at") or "")
        if not expires_at or expires_at > now:
            continue
        result.pop("encrypted_generated_password", None)
        result["credentials_expired_at"] = now
        result["credentials_pending_delivery"] = False
        db.execute(
            "UPDATE migration_users SET result_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(result), row["id"]),
        )
        cleaned += 1
    return cleaned


def run(task_id: int, db):
    task_logs(task_id, "start", "Migration worker started")
    usage_validated = reconcile_destination_usage(db)
    jobs_reconciled = reconcile_source_jobs(db)
    credentials_cleaned = _cleanup_expired_credentials(db)
    db.execute(
        """
        UPDATE migration_campaigns
        SET status='running', started_at=COALESCE(started_at,CURRENT_TIMESTAMP),
            updated_at=CURRENT_TIMESTAMP
        WHERE status='scheduled'
          AND scheduled_at IS NOT NULL
          AND datetime(scheduled_at) <= CURRENT_TIMESTAMP
        """
    )
    campaigns = {
        int(row["id"])
        for row in db.query("SELECT id FROM migration_campaigns WHERE status IN ('running','waiting_users')")
    }
    rows = db.query(
        """
        SELECT
          mu.*,
          mc.source_server_id, mc.destination_server_id,
          mc.migration_type, mc.migration_mode, mc.status AS campaign_status,
          mc.batch_size,
          destination.type AS destination_type
        FROM migration_users mu
        JOIN migration_campaigns mc ON mc.id = mu.campaign_id
        JOIN servers destination ON destination.id = mc.destination_server_id
        WHERE (
            (mc.status = 'running' AND mu.status = 'pending')
            OR
            (mc.status = 'waiting_users' AND mu.status = 'waiting_acceptance'
             AND mu.updated_at <= datetime('now','-10 minutes'))
          )
          AND mu.eligibility IN ('ready','already_present')
        ORDER BY mc.id, mu.id
        LIMIT 100
        """
    )
    processed = 0
    failed = 0
    processed_by_campaign = {}
    for row in rows:
        migration_user = dict(row)
        campaign_id = int(migration_user["campaign_id"])
        batch_size = max(1, int(migration_user.get("batch_size") or 10))
        if processed_by_campaign.get(campaign_id, 0) >= batch_size:
            continue
        campaigns.add(campaign_id)
        claim = db.execute(
            "UPDATE migration_users SET status='processing', started_at=COALESCE(started_at,CURRENT_TIMESTAMP), attempts=attempts+1, last_error=NULL WHERE id=? AND status=?",
            (migration_user["id"], migration_user["status"]),
        )
        if getattr(claim, "rowcount", 0) != 1:
            continue
        processed_by_campaign[campaign_id] = processed_by_campaign.get(campaign_id, 0) + 1
        try:
            campaign = {**migration_user, "id": campaign_id}
            final_status = process_migration_user(db, campaign, migration_user)
            db.execute(
                "UPDATE migration_users SET status=?, completed_at=CASE WHEN ?='completed' THEN CURRENT_TIMESTAMP ELSE completed_at END, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (final_status, final_status, migration_user["id"]),
            )
            processed += 1
        except Exception as exc:
            failed += 1
            retry_status = "waiting_acceptance" if migration_user["status"] == "waiting_acceptance" else "failed"
            db.execute(
                "UPDATE migration_users SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (retry_status, str(exc)[:2000], migration_user["id"]),
            )
            log.error("Migration user %s failed: %s", migration_user["id"], exc, exc_info=True)

    for campaign_id in campaigns:
        refresh_campaign_status(db, campaign_id)
    active = db.query_one(
        """
        SELECT COUNT(*) AS total
        FROM migration_users mu
        JOIN migration_campaigns mc ON mc.id=mu.campaign_id
        WHERE (mc.status='running' AND mu.status='pending')
           OR (mc.status='waiting_users' AND mu.status IN ('waiting_acceptance','waiting_validation'))
           OR mc.status='scheduled'
        """
    )
    try:
        active_jobs = db.query_one(
            """
            SELECT COUNT(*) AS total FROM media_jobs
            WHERE status IN ('queued','running')
              AND payload_json LIKE '%"reason": "migration_phase3"%'
            """
        )
    except Exception:
        active_jobs = None
    if (
        (not active or int(active["total"] or 0) == 0)
        and (not active_jobs or int(active_jobs["total"] or 0) == 0)
    ):
        db.execute("UPDATE tasks SET enabled=0 WHERE name='migration_worker'")
    result = {
        "processed": processed,
        "failed": failed,
        "usage_validated": usage_validated,
        "jobs_reconciled": jobs_reconciled,
        "credentials_cleaned": credentials_cleaned,
    }
    task_logs(task_id, "info", "Migration worker finished", details=result)
    return result
