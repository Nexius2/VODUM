"""Conservative recovery of scheduled emails that exhausted normal retries."""

from notifications_utils import is_email_ready


def retry_failed_scheduled_communications(db):
    """Give every failed scheduled communication a fresh normal retry cycle."""
    cur = db.execute(
        """
        UPDATE comm_scheduled
        SET status = 'pending',
            attempt_count = 0,
            next_attempt_at = NULL,
            last_attempt_at = NULL,
            last_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'error'
        """
    )
    return int(getattr(cur, "rowcount", 0) or 0)


def recover_missed_scheduled_emails(
    db,
    settings,
    *,
    max_age_days=30,
    max_catchups=3,
    cooldown_hours=24,
    limit=100,
):
    """
    Requeue final email failures after SMTP or recipient configuration recovers.

    Normal retry backoff remains untouched. Recovery is bounded by age, number
    of catch-up cycles and a cooldown so permanently invalid addresses cannot
    create an endless retry loop.
    """
    if not is_email_ready(settings or {}):
        return {"requeued": 0, "reason": "email_not_ready"}

    rows = db.query(
        """
        SELECT q.id
        FROM comm_scheduled q
        JOIN comm_templates t ON t.id = q.template_id
        JOIN vodum_users u ON u.id = q.vodum_user_id
        WHERE q.status = 'error'
          AND COALESCE(q.attempt_count, 0) >= COALESCE(q.max_attempts, 10)
          AND COALESCE(q.catchup_count, 0) < ?
          AND datetime(q.send_at) >= datetime('now', ?)
          AND (
                q.last_catchup_at IS NULL
             OR datetime(q.last_catchup_at) <= datetime('now', ?)
          )
          AND t.enabled = 1
          AND (
                TRIM(COALESCE(u.email, '')) <> ''
             OR TRIM(COALESCE(u.second_email, '')) <> ''
          )
          AND INSTR(',' || LOWER(COALESCE(q.channels_sent, '')) || ',', ',email,') = 0
        ORDER BY datetime(q.send_at) ASC, q.id ASC
        LIMIT ?
        """,
        (
            int(max_catchups),
            f"-{int(max_age_days)} days",
            f"-{int(cooldown_hours)} hours",
            int(limit),
        ),
    ) or []

    requeued = 0
    for row in rows:
        cur = db.execute(
            """
            UPDATE comm_scheduled
            SET status = 'pending',
                attempt_count = 0,
                next_attempt_at = NULL,
                last_attempt_at = NULL,
                last_error = NULL,
                catchup_count = COALESCE(catchup_count, 0) + 1,
                last_catchup_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'error'
              AND COALESCE(attempt_count, 0) >= COALESCE(max_attempts, 10)
              AND COALESCE(catchup_count, 0) < ?
            """,
            (int(row["id"]), int(max_catchups)),
        )
        if int(getattr(cur, "rowcount", 0) or 0) == 1:
            requeued += 1

    return {"requeued": requeued, "reason": None}
