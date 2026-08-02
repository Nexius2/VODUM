def ensure_subscription_gift_schema(conn, cursor, *, table_exists) -> None:
    if not table_exists(cursor, "subscription_gift_runs"):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_gift_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              target_type TEXT NOT NULL,
              target_server_id INTEGER NULL,
              days_added INTEGER NOT NULL,
              reason TEXT NULL,
              users_updated INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

    if not table_exists(cursor, "subscription_gift_run_users"):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_gift_run_users (
              run_id INTEGER NOT NULL,
              vodum_user_id INTEGER NOT NULL,
              PRIMARY KEY (run_id, vodum_user_id)
            )
        """)
        conn.commit()
