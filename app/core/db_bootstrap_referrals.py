from __future__ import annotations


def ensure_referral_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
    ensure_row,
):
    # -------------------------------------------------
    # USER REFERRAL SETTINGS
    # -------------------------------------------------
    if not table_exists(cursor, "user_referral_settings"):
        print("🛠 Creating table: user_referral_settings")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_referral_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),

            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            reward_enabled INTEGER NOT NULL DEFAULT 1 CHECK(reward_enabled IN (0,1)),
            qualification_days INTEGER NOT NULL DEFAULT 60,
            reward_days INTEGER NOT NULL DEFAULT 60,

            allow_referrer_change_before_qualification INTEGER NOT NULL DEFAULT 1 CHECK(allow_referrer_change_before_qualification IN (0,1)),
            auto_notify_reward INTEGER NOT NULL DEFAULT 1 CHECK(auto_notify_reward IN (0,1)),

            eligible_statuses TEXT NOT NULL DEFAULT 'active',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

    ensure_row(cursor, "user_referral_settings", "id = :id", {
        "id": 1,
        "enabled": 0,
        "reward_enabled": 1,
        "qualification_days": 60,
        "reward_days": 60,
        "allow_referrer_change_before_qualification": 1,
        "auto_notify_reward": 1,
        "eligible_statuses": "active",
    })
    conn.commit()

    # -------------------------------------------------
    # USER REFERRALS
    # -------------------------------------------------
    if not table_exists(cursor, "user_referrals"):
        print("🛠 Creating table: user_referrals")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            referrer_user_id INTEGER NOT NULL,
            referred_user_id INTEGER NOT NULL UNIQUE,

            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN (
                    'pending',
                    'qualified',
                    'rewarded',
                    'expired',
                    'archived',
                    'cancelled'
                )),

            referral_source TEXT DEFAULT 'manual',

            start_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            qualification_due_at TIMESTAMP,
            qualified_at TIMESTAMP DEFAULT NULL,

            qualification_days_snapshot INTEGER NOT NULL DEFAULT 60,
            reward_days_snapshot INTEGER NOT NULL DEFAULT 60,

            reward_granted_at TIMESTAMP DEFAULT NULL,
            reward_expiration_before TEXT DEFAULT NULL,
            reward_expiration_after TEXT DEFAULT NULL,

            expired_at TIMESTAMP DEFAULT NULL,
            archived_at TIMESTAMP DEFAULT NULL,

            notification_sent_at TIMESTAMP DEFAULT NULL,
            notification_template_id INTEGER DEFAULT NULL,
            last_error TEXT DEFAULT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(referrer_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
            FOREIGN KEY(referred_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referrals_referrer_user_id ON user_referrals(referrer_user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referrals_status ON user_referrals(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referrals_qualification_due_at ON user_referrals(qualification_due_at);")
        conn.commit()

    ensure_column(cursor, "user_referrals", "notification_template_id", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "user_referrals", "last_error", "TEXT DEFAULT NULL")
    ensure_column(cursor, "user_referrals", "expired_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "user_referrals", "archived_at", "TIMESTAMP DEFAULT NULL")

    # -------------------------------------------------
    # MIGRATION: refresh old referral status CHECK constraint
    # SQLite cannot ALTER CHECK constraints directly
    # -------------------------------------------------

    try:
        cursor.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type='table'
              AND name='user_referrals'
        """)

        row = cursor.fetchone()
        table_sql = (row[0] or "") if row else ""

        if (
            "'expired'" not in table_sql
            or "'archived'" not in table_sql
        ):

            print("🛠 Migrating user_referrals CHECK constraint...")

            cursor.execute("""
                ALTER TABLE user_referrals
                RENAME TO user_referrals_old
            """)

            cursor.execute("""
            CREATE TABLE user_referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                referrer_user_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,

                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN (
                        'pending',
                        'qualified',
                        'rewarded',
                        'expired',
                        'archived',
                        'cancelled'
                    )),

                referral_source TEXT DEFAULT 'manual',

                start_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                qualification_due_at TIMESTAMP,
                qualified_at TIMESTAMP DEFAULT NULL,

                qualification_days_snapshot INTEGER NOT NULL DEFAULT 60,
                reward_days_snapshot INTEGER NOT NULL DEFAULT 60,

                reward_granted_at TIMESTAMP DEFAULT NULL,
                reward_expiration_before TEXT DEFAULT NULL,
                reward_expiration_after TEXT DEFAULT NULL,

                expired_at TIMESTAMP DEFAULT NULL,
                archived_at TIMESTAMP DEFAULT NULL,

                notification_sent_at TIMESTAMP DEFAULT NULL,
                notification_template_id INTEGER DEFAULT NULL,
                last_error TEXT DEFAULT NULL,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(referrer_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
                FOREIGN KEY(referred_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
            );
            """)

            cursor.execute("""
                INSERT INTO user_referrals (
                    id,
                    referrer_user_id,
                    referred_user_id,
                    status,
                    referral_source,
                    start_at,
                    qualification_due_at,
                    qualified_at,
                    qualification_days_snapshot,
                    reward_days_snapshot,
                    reward_granted_at,
                    reward_expiration_before,
                    reward_expiration_after,
                    expired_at,
                    archived_at,
                    notification_sent_at,
                    notification_template_id,
                    last_error,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    referrer_user_id,
                    referred_user_id,
                    status,
                    referral_source,
                    start_at,
                    qualification_due_at,
                    qualified_at,
                    qualification_days_snapshot,
                    reward_days_snapshot,
                    reward_granted_at,
                    reward_expiration_before,
                    reward_expiration_after,
                    expired_at,
                    archived_at,
                    notification_sent_at,
                    notification_template_id,
                    last_error,
                    created_at,
                    updated_at
                FROM user_referrals_old
            """)

            cursor.execute("DROP TABLE user_referrals_old")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_referrals_referrer_user_id
                ON user_referrals(referrer_user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_referrals_status
                ON user_referrals(status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_referrals_qualification_due_at
                ON user_referrals(qualification_due_at)
            """)

            conn.commit()

            print("✅ user_referrals CHECK constraint migrated")

    except Exception as e:
        print(f"âŒ Failed migrating user_referrals constraint: {e}")

    ensure_column(cursor, "user_referral_settings", "auto_expire_pending", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(cursor, "user_referral_settings", "auto_archive_rewarded", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(cursor, "user_referral_settings", "auto_archive_expired", "INTEGER NOT NULL DEFAULT 1")

    ensure_column(cursor, "user_referral_settings", "pending_expire_days", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(cursor, "user_referral_settings", "rewarded_archive_days", "INTEGER NOT NULL DEFAULT 90")
    ensure_column(cursor, "user_referral_settings", "expired_archive_days", "INTEGER NOT NULL DEFAULT 30")

    conn.commit()
