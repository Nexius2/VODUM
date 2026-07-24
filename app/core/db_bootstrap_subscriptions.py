from __future__ import annotations


def ensure_subscription_template_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
):
    # -------------------------------------------------
    # 1.3 Subscription templates (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "subscription_templates"):
        print("🛠 Creating table: subscription_templates")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_templates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          notes TEXT,
          duration_days INTEGER DEFAULT 30,
          subscription_value REAL DEFAULT 0,
          policies_json TEXT NOT NULL DEFAULT '[]',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

    ensure_column(cursor, "subscription_templates", "duration_days", "INTEGER DEFAULT 30")
    ensure_column(cursor, "subscription_templates", "subscription_value", "REAL DEFAULT 0")
    ensure_column(cursor, "subscription_templates", "is_default", "INTEGER DEFAULT 0")
    ensure_column(cursor, "subscription_templates", "is_enabled", "INTEGER DEFAULT 1")
    ensure_column(cursor, "subscription_templates", "is_lifetime", "INTEGER DEFAULT 0")
    conn.commit()

    # Seed marker: default subscription templates must be inserted only once.
    # If the admin deletes them later, they must not come back automatically at next boot.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_template_seed_state (
            seed_key TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    bundled_templates = [
        (
            "base sub",
            "2 streams / Same IP",
            365,
            10,
            0,
            0,
            '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}},{"rule_type":"max_streams_per_ip","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
        ),
        (
            "Family sub",
            "4 streams",
            365,
            30,
            0,
            0,
            '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":4,"allow_local_ip":true}}]',
        ),
        (
            "Plus sub",
            "3 streams / 2 IP",
            365,
            20,
            0,
            0,
            '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":3,"allow_local_ip":true}},{"rule_type":"max_ips_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
        ),
    ]

    cursor.execute(
        "SELECT seed_key FROM subscription_template_seed_state WHERE seed_key = ?",
        ("default_subscription_templates",),
    )
    default_templates_already_seeded = cursor.fetchone() is not None

    if not default_templates_already_seeded:
        cursor.execute("SELECT COUNT(*) FROM subscription_templates")
        templates_count = int(cursor.fetchone()[0] or 0)

        if templates_count == 0:
            print("🛠 Creating bundled default subscription templates")
            for name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json in bundled_templates:
                cursor.execute(
                    """
                    INSERT INTO subscription_templates(
                        name,
                        notes,
                        duration_days,
                        subscription_value,
                        is_default,
                        is_enabled,
                        policies_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        notes,
                        duration_days,
                        subscription_value,
                        is_default,
                        is_enabled,
                        policies_json,
                    ),
                )

        cursor.execute(
            "INSERT OR IGNORE INTO subscription_template_seed_state(seed_key) VALUES (?)",
            ("default_subscription_templates",),
        )
        conn.commit()
