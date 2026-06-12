"""Operational controls for migration campaigns."""

from __future__ import annotations

import json


ACTIVE_CAMPAIGN_STATUSES = ("scheduled", "running", "paused", "waiting_users", "needs_attention")


def conflicting_active_users(db, campaign_id: int) -> list[dict]:
    return [
        dict(row)
        for row in db.query(
            """
            SELECT DISTINCT mu.vodum_user_id, other.id AS campaign_id, other.name AS campaign_name
            FROM migration_campaigns current
            JOIN migration_users mu ON mu.campaign_id=current.id
            JOIN migration_campaigns other
              ON other.id<>current.id
             AND other.destination_server_id=current.destination_server_id
             AND other.status IN ('scheduled','running','paused','waiting_users','needs_attention')
            JOIN migration_users other_user
              ON other_user.campaign_id=other.id
             AND other_user.vodum_user_id=mu.vodum_user_id
             AND other_user.status NOT IN ('excluded','completed')
            WHERE current.id=?
              AND mu.status<>'excluded'
            ORDER BY other.id, mu.vodum_user_id
            """,
            (int(campaign_id),),
        )
    ]


def pause_campaign(db, campaign_id: int) -> None:
    cursor = db.execute(
        """
        UPDATE migration_campaigns
        SET status='paused', updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND status IN ('scheduled','running','waiting_users','needs_attention')
        """,
        (int(campaign_id),),
    )
    if getattr(cursor, "rowcount", 0) != 1:
        raise ValueError("This migration campaign cannot be paused.")


def resume_campaign(db, campaign_id: int) -> str:
    conflicts = conflicting_active_users(db, campaign_id)
    if conflicts:
        raise ValueError("Another active campaign targets one or more of these users on the same destination.")
    cursor = db.execute(
        """
        UPDATE migration_campaigns
        SET status=CASE
              WHEN scheduled_at IS NOT NULL AND datetime(scheduled_at)>CURRENT_TIMESTAMP THEN 'scheduled'
              ELSE 'running'
            END,
            started_at=CASE
              WHEN scheduled_at IS NULL OR datetime(scheduled_at)<=CURRENT_TIMESTAMP
                THEN COALESCE(started_at,CURRENT_TIMESTAMP)
              ELSE started_at
            END,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND status='paused'
        """,
        (int(campaign_id),),
    )
    if getattr(cursor, "rowcount", 0) != 1:
        raise ValueError("This migration campaign cannot be resumed.")
    row = db.query_one("SELECT status FROM migration_campaigns WHERE id=?", (int(campaign_id),))
    return str(row["status"])


def retry_failed_users(db, campaign_id: int) -> int:
    campaign = db.query_one("SELECT status FROM migration_campaigns WHERE id=?", (int(campaign_id),))
    if not campaign or str(campaign["status"] or "") not in {"needs_attention", "paused", "running"}:
        raise ValueError("Failed users cannot be retried in this campaign state.")
    conflicts = conflicting_active_users(db, campaign_id)
    if conflicts:
        raise ValueError("Another active campaign targets one or more of these users on the same destination.")
    cursor = db.execute(
        """
        UPDATE migration_users
        SET status='pending', last_error=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE campaign_id=? AND status='failed' AND eligibility IN ('ready','already_present')
        """,
        (int(campaign_id),),
    )
    count = max(0, int(getattr(cursor, "rowcount", 0) or 0))
    if count:
        db.execute(
            "UPDATE migration_campaigns SET status='running',completed_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (int(campaign_id),),
        )
    return count


def set_user_excluded(db, campaign_id: int, migration_user_id: int, excluded: bool) -> None:
    row = db.query_one(
        """
        SELECT mu.status,mu.eligibility,mu.blockers_json,mu.options_json,mc.status AS campaign_status
        FROM migration_users mu
        JOIN migration_campaigns mc ON mc.id=mu.campaign_id
        WHERE mu.id=? AND mu.campaign_id=?
        """,
        (int(migration_user_id), int(campaign_id)),
    )
    if not row:
        raise ValueError("Migration user not found.")
    if str(row["campaign_status"] or "") not in {"draft", "scheduled", "running", "paused", "needs_attention"}:
        raise ValueError("Users cannot be included or excluded in this campaign state.")
    current_status = str(row["status"] or "")
    if current_status in {"processing", "waiting_acceptance", "waiting_validation", "completed"}:
        raise ValueError("This migration user can no longer be excluded.")
    try:
        options = json.loads(row["options_json"] or "{}")
    except Exception:
        options = {}
    if excluded:
        options["eligibility_before_exclusion"] = str(row["eligibility"] or "ready")
        options["status_before_exclusion"] = current_status
        db.execute(
            "UPDATE migration_users SET eligibility='excluded',status='excluded',options_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(options), int(migration_user_id)),
        )
        return
    if current_status != "excluded":
        raise ValueError("This migration user is not excluded.")
    eligibility = str(options.pop("eligibility_before_exclusion", "") or "")
    if eligibility not in {"ready", "blocked", "already_present"}:
        blockers = json.loads(row["blockers_json"] or "[]")
        eligibility = "blocked" if blockers else "ready"
    status = "pending"
    db.execute(
        "UPDATE migration_users SET eligibility=?,status=?,options_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (eligibility, status, json.dumps(options), int(migration_user_id)),
    )
