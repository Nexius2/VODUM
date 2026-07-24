TASK_DEFAULTS_VERSION = 4

TASK_SCHEDULE_DEFAULTS = {
    "sync_plex": "7 */6 * * *",
    "sync_jellyfin": "17 */6 * * *",
    "check_update": "0 4 * * *",
    "auto_backup": "0 3 */3 * *",
    "cleanup_backups": "30 3 * * *",
    "cleanup_data_retention": "0 4 * * 0",
    "db_integrity_check": "15 4 * * 0",
    "cleanup_artwork_cache": "30 4 * * 0",
    "warmup_artwork_cache": "*/30 * * * *",
    "cleanup_tautulli_imports": "45 4 * * 0",
    "cleanup_data_consistency": "50 4 * * 0",
    "update_user_status": "5 * * * *",
    "check_servers": "7,37 * * * *",
    "cleanup_unfriended": "0 4 * * *",
    "monitor_enqueue_refresh": "*/1 * * * *",
    "media_jobs_worker": "*/1 * * * *",
    "send_pending_invite_reminders": "30 0 * * *",
    "check_mailing_status": "9 * * * *",
    "expired_subscription_manager": "13 * * * *",
    "send_telemetry": "23 * * * *",
    "send_expiration_emails": "27 * * * *",
    "usage_risk_notifications": "19,49 * * * *",
    "send_comm_campaigns": "*/10 * * * *",
}

TASK_SCHEDULE_LEGACY_DEFAULTS = {
    "monitor_enqueue_refresh": {"*/3 * * * *", "*/1 * * * *"},
    "media_jobs_worker": {"*/1 * * * *"},
    "check_servers": {"*/10 * * * *", "*/30 * * * *"},
    "send_pending_invite_reminders": {"0 30 * * *", "30 * * *", "30 0 * * *"},
    "send_telemetry": {"0 0 * * *", "0 * * * *"},
    "sync_plex": {"0 */6 * * *"},
    "sync_jellyfin": {"0 */6 * * *"},
    "update_user_status": {"0 * * * *"},
    "check_mailing_status": {"0 * * * *"},
    "expired_subscription_manager": {"0 */1 * * *"},
    "send_expiration_emails": {"0 * * * *"},
    "usage_risk_notifications": {"*/30 * * * *"},
}


def migrate_task_schedule_defaults(conn, cursor) -> None:
    cursor.execute("SELECT COALESCE(task_defaults_version, 0) FROM settings WHERE id = 1")
    row = cursor.fetchone()
    current_version = int(row[0]) if row and row[0] is not None else 0

    if current_version < TASK_DEFAULTS_VERSION:
        print(f"Applying task schedule defaults migration v{TASK_DEFAULTS_VERSION}...")
        for task_name, new_schedule in TASK_SCHEDULE_DEFAULTS.items():
            cursor.execute("SELECT schedule FROM tasks WHERE name = ?", (task_name,))
            task_row = cursor.fetchone()
            if not task_row:
                continue
            current_schedule = task_row[0]
            allowed = TASK_SCHEDULE_LEGACY_DEFAULTS.get(task_name, {new_schedule})
            if current_schedule in allowed:
                cursor.execute(
                    """
                    UPDATE tasks
                    SET schedule = ?, next_run = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE name = ?
                    """,
                    (new_schedule, task_name),
                )
                print(f"Task schedule updated: {task_name} -> {new_schedule}")
            else:
                print(f"Task schedule kept unchanged (custom): {task_name} -> {current_schedule}")
        cursor.execute(
            "UPDATE settings SET task_defaults_version = ? WHERE id = 1",
            (TASK_DEFAULTS_VERSION,),
        )
        conn.commit()

    if current_version < 4:
        cursor.execute("""
            UPDATE tasks
            SET schedule_mode = 'interval', interval_seconds = 15,
                next_run = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE name IN ('monitor_enqueue_refresh', 'media_jobs_worker')
              AND (interval_seconds IS NULL OR interval_seconds IN (60, 120, 180))
        """)
        cursor.execute("""
            UPDATE tasks
            SET schedule_mode = 'interval', interval_seconds = 15,
                next_run = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE name = 'stream_enforcer'
              AND (interval_seconds IS NULL OR interval_seconds IN (15, 60, 120))
        """)
        conn.commit()
