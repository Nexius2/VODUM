from __future__ import annotations


def ensure_referral_event_schema(conn, cursor, *, table_exists):
    # -------------------------------------------------
    # USER REFERRAL EVENTS
    # -------------------------------------------------
    if not table_exists(cursor, "user_referral_events"):
        print("🛠 Creating table: user_referral_events")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_referral_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            referral_id INTEGER NOT NULL,
            event_type TEXT NOT NULL
                CHECK(event_type IN (
                    'created',
                    'referrer_changed',
                    'qualified',
                    'reward_granted',
                    'notification_sent',
                    'cancelled'
                )),

            actor TEXT DEFAULT 'system',
            old_referrer_user_id INTEGER DEFAULT NULL,
            new_referrer_user_id INTEGER DEFAULT NULL,
            details_json TEXT DEFAULT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(referral_id) REFERENCES user_referrals(id) ON DELETE CASCADE,
            FOREIGN KEY(old_referrer_user_id) REFERENCES vodum_users(id) ON DELETE SET NULL,
            FOREIGN KEY(new_referrer_user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referral_events_referral_id ON user_referral_events(referral_id);")
        conn.commit()
