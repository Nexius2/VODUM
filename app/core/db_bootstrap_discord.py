def ensure_discord_schema(conn, cursor, *, table_exists, ensure_column) -> None:
    ensure_column(cursor, "settings", "discord_enabled", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "discord_bot_token", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "discord_bot_id", "INTEGER DEFAULT NULL")

    if not table_exists(cursor, "discord_bots"):
        print("Creating table: discord_bots")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discord_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token TEXT DEFAULT NULL,
                bot_user_id TEXT DEFAULT NULL,
                bot_username TEXT DEFAULT NULL,
                bot_type TEXT NOT NULL DEFAULT 'custom' CHECK(bot_type IN ('custom','vodum')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_discord_bots_type ON discord_bots(bot_type)")
        conn.commit()

    try:
        cursor.execute("SELECT discord_bot_id, discord_bot_token FROM settings WHERE id = 1")
        settings_row = cursor.fetchone()
        legacy_bot_id = settings_row[0] if settings_row else None
        legacy_token = (settings_row[1] or "").strip() if settings_row else ""
        if (legacy_bot_id is None or legacy_bot_id == 0) and legacy_token:
            cursor.execute(
                "INSERT INTO discord_bots(name, token, bot_type) VALUES(?, ?, 'custom')",
                ("Primary bot", legacy_token),
            )
            cursor.execute("UPDATE settings SET discord_bot_id = ? WHERE id = 1", (cursor.lastrowid,))
            conn.commit()
            print("Migrated legacy discord_bot_token into discord_bots (Primary bot)")
    except Exception as exc:
        print(f"Discord bots migration skipped: {exc}")

    ensure_column(cursor, "settings", "notifications_order", "TEXT DEFAULT 'email'")
    ensure_column(cursor, "settings", "user_notifications_can_override", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "notifications_send_mode", "TEXT DEFAULT 'first'")
    cursor.execute("UPDATE settings SET notifications_order = COALESCE(NULLIF(TRIM(notifications_order),''), 'email') WHERE id = 1")
    ensure_column(cursor, "settings", "expiry_mode", "TEXT DEFAULT 'disable'")
    ensure_column(cursor, "settings", "warn_then_disable_days", "INTEGER DEFAULT 7")
    ensure_column(cursor, "vodum_users", "discord_user_id", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "discord_name", "TEXT DEFAULT NULL")

    if not table_exists(cursor, "discord_templates"):
        print("Creating table: discord_templates")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discord_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT UNIQUE NOT NULL CHECK(type IN ('preavis','relance','fin')),
                title TEXT,
                body TEXT
            )
        """)
        conn.commit()

    if not table_exists(cursor, "sent_discord"):
        print("Creating table: sent_discord")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sent_discord (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                template_type TEXT NOT NULL,
                expiration_date TEXT,
                sent_at INTEGER,
                UNIQUE(user_id, template_type, expiration_date),
                FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
            )
        """)
        conn.commit()

    if not table_exists(cursor, "discord_campaigns"):
        print("Creating table: discord_campaigns")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discord_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                server_id INTEGER,
                is_test INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending','sent','failed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                error TEXT,
                FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
            )
        """)
        conn.commit()

    defaults = {
        "preavis": (
            "â³ Subscription expiring soon",
            "Hi {username}! You have {days_left} day(s) left. Your subscription expires on {expiration_date}.",
        ),
        "relance": (
            "🔔 Subscription reminder",
            "Hello {username} 🙂 Just a reminder: your subscription expires on {expiration_date} ({days_left} day(s) left).",
        ),
        "fin": (
            "âš ï¸ Subscription expired",
            "Hi {username}. Your subscription expired on {expiration_date}. Please contact me to renew it.",
        ),
    }
    for template_type, (title, body) in defaults.items():
        cursor.execute("SELECT 1 FROM discord_templates WHERE type=?", (template_type,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO discord_templates(type, title, body) VALUES(?,?,?)",
                (template_type, title, body),
            )
            print(f"Default discord template inserted: {template_type}")
    conn.commit()
