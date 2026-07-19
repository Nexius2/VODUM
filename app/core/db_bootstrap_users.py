from __future__ import annotations


def upgrade_vodum_user_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
):
    # -------------------------------------------------
    # 1.1 Upgrade vodum_users.status CHECK constraint (NEW statuses)
    # -------------------------------------------------
    def vodum_users_has_new_statuses():
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='vodum_users'")
        row = cursor.fetchone()
        if not row or not row[0]:
            return False
        sql = row[0].lower()
        return ("'invited'" in sql) and ("'unknown'" in sql)

    if table_exists(cursor, "vodum_users") and not vodum_users_has_new_statuses():
        print("🛠 Upgrading vodum_users.status CHECK (add invited/unfriended/suspended/unknown)")
        cursor.execute("ALTER TABLE vodum_users RENAME TO vodum_users_old")

        cursor.execute("""
        CREATE TABLE vodum_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT,
            firstname TEXT,
            lastname TEXT,
            email TEXT,
            second_email TEXT,

            expiration_date TIMESTAMP,
            renewal_method TEXT,
            renewal_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            notes TEXT,

            status TEXT DEFAULT 'expired'
              CHECK (status IN (
                'active','pre_expired','reminder','expired',
                'invited','unfriended','suspended','unknown'
              )),
            last_status TEXT,
            status_changed_at TIMESTAMP
        );
        """)

        cursor.execute("""
        INSERT INTO vodum_users (
            id, username, firstname, lastname, email, second_email,
            expiration_date, renewal_method, renewal_date, created_at,
            notes, status, last_status, status_changed_at
        )
        SELECT
            id, username, firstname, lastname, email, second_email,
            expiration_date, renewal_method, renewal_date, created_at,
            notes, status, last_status, status_changed_at
        FROM vodum_users_old;
        """)

        cursor.execute("DROP TABLE vodum_users_old")
        conn.commit()
        print("✔ vodum_users.status constraint upgraded.")

    # 1.2 vodum_users per-user stream override
    ensure_column(cursor, "vodum_users", "max_streams_override", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "notifications_order_override", "TEXT DEFAULT NULL")

    # vodum_users per-user expiration date override
    ensure_column(cursor, "vodum_users", "expiration_date_override", "INTEGER DEFAULT 0")

    # Missing columns on upgraded databases
    ensure_column(cursor, "vodum_users", "renewal_method", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "renewal_date", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "referrer_user_id", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "last_status", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "status_changed_at", "TIMESTAMP DEFAULT NULL")

    # Subscription template assignment
    ensure_column(cursor, "vodum_users", "subscription_template_id", "INTEGER DEFAULT NULL")
