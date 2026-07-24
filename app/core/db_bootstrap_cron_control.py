def enforce_global_cron_setting(conn, cursor) -> None:
    try:
        cursor.execute("SELECT enable_cron_jobs FROM settings WHERE id = 1")
        row = cursor.fetchone()
        cron_enabled = int(row[0]) if row and row[0] is not None else 1
    except Exception:
        cron_enabled = 1

    if cron_enabled != 0:
        return

    cursor.execute("""
        UPDATE tasks
        SET enabled_prev = CASE
                WHEN enabled_prev IS NULL THEN enabled
                ELSE enabled_prev
            END,
            enabled = 0,
            status = 'disabled',
            updated_at = CURRENT_TIMESTAMP
    """)
    conn.commit()
    print("Cron disabled: all tasks forced to disabled (state remembered).")
