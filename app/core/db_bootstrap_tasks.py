from __future__ import annotations


def migrate_task_scheduler_mode(conn, cursor, *, ensure_column):
    # -------------------------------------------------
    # Tasks scheduler mode migrations
    # -------------------------------------------------

    ensure_column(cursor, "tasks", "schedule_mode", "TEXT DEFAULT 'cron'")
    ensure_column(cursor, "tasks", "interval_seconds", "INTEGER DEFAULT NULL")

    cursor.execute("""
        UPDATE tasks
        SET schedule_mode = 'cron'
        WHERE schedule_mode IS NULL
    """)

    conn.commit()

    # -------------------------------------------------
    # Convert worker tasks to interval mode
    # -------------------------------------------------

    cursor.execute("""
        UPDATE tasks
        SET
            schedule_mode = 'interval',
            interval_seconds = CASE
                WHEN name = 'stream_enforcer' THEN 15
                ELSE 15
            END
        WHERE name IN (
            'monitor_enqueue_refresh',
            'media_jobs_worker',
            'stream_enforcer'
        )
        AND (
            schedule_mode IS NULL
            OR schedule_mode = 'cron'
            OR name = 'stream_enforcer'
        )
    """)

    cursor.execute("""
        UPDATE tasks
        SET
            schedule_mode = 'interval',
            interval_seconds = 120
        WHERE name = 'apply_plex_access_updates'
        AND (
            schedule_mode IS NULL
            OR schedule_mode = 'cron'
        )
    """)

    conn.commit()
