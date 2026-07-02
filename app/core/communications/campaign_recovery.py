"""Idempotent recovery for interrupted communication campaigns."""

from __future__ import annotations


def _campaign_target_summary(db, campaign_id: int) -> dict:
    row = db.query_one(
        """
        SELECT
          COUNT(*) AS total_count,
          SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent_count,
          SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
          SUM(CASE
                WHEN status='error'
                 AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, 10)
                THEN 1 ELSE 0
              END) AS retryable_count,
          SUM(CASE
                WHEN status='error'
                 AND COALESCE(attempt_count, 0) >= COALESCE(max_attempts, 10)
                THEN 1 ELSE 0
              END) AS final_error_count
        FROM comm_campaign_targets
        WHERE campaign_id=?
        """,
        (campaign_id,),
    )
    return dict(row) if row else {}


def recover_campaigns(db, *, stale_test_minutes: int = 30) -> dict:
    """Repair interrupted campaign states without rebuilding or resending sent targets."""
    stats = {
        "test_campaigns_requeued": 0,
        "retry_dates_repaired": 0,
        "campaigns_reconciled": 0,
    }

    cursor = db.execute(
        """
        UPDATE comm_campaigns
        SET status='pending',
            sent_at=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE is_test=1
          AND status='sending'
          AND datetime(updated_at) <= datetime('now', ?)
        """,
        (f"-{max(1, int(stale_test_minutes))} minutes",),
    )
    stats["test_campaigns_requeued"] = max(0, int(getattr(cursor, "rowcount", 0) or 0))

    cursor = db.execute(
        """
        UPDATE comm_campaign_targets
        SET next_attempt_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE status='error'
          AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, 10)
          AND next_attempt_at IS NULL
        """
    )
    stats["retry_dates_repaired"] = max(0, int(getattr(cursor, "rowcount", 0) or 0))

    campaigns = db.query(
        """
        SELECT DISTINCT c.id, c.status
        FROM comm_campaigns c
        JOIN comm_campaign_targets ct ON ct.campaign_id=c.id
        WHERE c.is_test=0
          AND c.status IN ('pending','sending','error','finished')
        ORDER BY c.id
        """
    ) or []

    for campaign_row in campaigns:
        campaign = dict(campaign_row)
        summary = _campaign_target_summary(db, int(campaign["id"]))
        total = int(summary.get("total_count") or 0)
        sent = int(summary.get("sent_count") or 0)
        pending = int(summary.get("pending_count") or 0)
        retryable = int(summary.get("retryable_count") or 0)
        final_errors = int(summary.get("final_error_count") or 0)

        if pending > 0 or retryable > 0:
            expected_status = "sending"
            sent_at_sql = "NULL"
        elif total > 0 and sent == total:
            expected_status = "finished"
            sent_at_sql = "COALESCE(sent_at, CURRENT_TIMESTAMP)"
        elif final_errors > 0:
            expected_status = "error"
            sent_at_sql = "COALESCE(sent_at, CURRENT_TIMESTAMP)"
        else:
            expected_status = "error"
            sent_at_sql = "COALESCE(sent_at, CURRENT_TIMESTAMP)"

        if (campaign.get("status") or "") == expected_status:
            continue
        db.execute(
            f"""
            UPDATE comm_campaigns
            SET status=?,
                sent_at={sent_at_sql},
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (expected_status, int(campaign["id"])),
        )
        stats["campaigns_reconciled"] += 1

    return stats
