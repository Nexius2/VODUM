from __future__ import annotations


def ensure_usage_risk_schema(conn, cursor, *, table_exists):
    # -------------------------------------------------
    # Usage risk recommendation history
    # -------------------------------------------------
    if not table_exists(cursor, "usage_risk_recommendations"):
        print("Creating table: usage_risk_recommendations")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_risk_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            vodum_user_id INTEGER NOT NULL,

            risk_level TEXT NOT NULL,
            risk_score INTEGER NOT NULL DEFAULT 0,

            current_subscription TEXT,
            suggested_subscription TEXT NOT NULL,

            first_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_notification_at TIMESTAMP DEFAULT NULL,

            cooldown_until TIMESTAMP DEFAULT NULL,

            status TEXT NOT NULL DEFAULT 'detected'
              CHECK(status IN ('detected','notified','ignored','resolved')),

            meta_json TEXT,

            FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_risk_recommendations_user
            ON usage_risk_recommendations(vodum_user_id, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_risk_recommendations_cooldown
            ON usage_risk_recommendations(cooldown_until)
        """)
        conn.commit()
