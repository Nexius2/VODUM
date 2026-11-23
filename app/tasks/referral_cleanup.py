from logging_utils import get_logger

logger = get_logger("referral_cleanup")


def run(task_id, db):

    logger.info("Referral cleanup started")

    settings = db.query_one(
        """
        SELECT id, enabled, reward_enabled, qualification_days, reward_days, allow_referrer_change_before_qualification, auto_notify_reward, eligible_statuses, created_at, updated_at, auto_expire_pending, auto_archive_rewarded, auto_archive_expired, pending_expire_days, rewarded_archive_days, expired_archive_days FROM user_referral_settings
        WHERE id = 1
        """
    )

    settings = dict(settings or {})

    # ---------------------------------------------------------
    # EXPIRE PENDING
    # ---------------------------------------------------------

    if int(settings.get("auto_expire_pending") or 0) == 1:

        db.execute(
            """
            UPDATE user_referrals
            SET
                status = 'expired',
                expired_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'pending'
              AND qualification_due_at IS NOT NULL
              AND datetime(qualification_due_at) < datetime('now')
            """
        )

    # ---------------------------------------------------------
    # ARCHIVE REWARDED
    # ---------------------------------------------------------

    if int(settings.get("auto_archive_rewarded") or 0) == 1:

        rewarded_days = int(
            settings.get("rewarded_archive_days") or 90
        )

        db.execute(
            f"""
            UPDATE user_referrals
            SET
                status = 'archived',
                archived_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'rewarded'
              AND reward_granted_at IS NOT NULL
              AND datetime(reward_granted_at)
                    < datetime('now', '-{rewarded_days} days')
            """
        )

    # ---------------------------------------------------------
    # ARCHIVE EXPIRED
    # ---------------------------------------------------------

    if int(settings.get("auto_archive_expired") or 0) == 1:

        expired_days = int(
            settings.get("expired_archive_days") or 30
        )

        db.execute(
            f"""
            UPDATE user_referrals
            SET
                status = 'archived',
                archived_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'expired'
              AND expired_at IS NOT NULL
              AND datetime(expired_at)
                    < datetime('now', '-{expired_days} days')
            """
        )

    logger.info("Referral cleanup completed")