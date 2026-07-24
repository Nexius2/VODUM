from __future__ import annotations


def upgrade_task_settings_auth_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
):
    # -------------------------------------------------
    # 2. Vérifier que toutes les colonnes obligatoires existent
    # -------------------------------------------------

    TASK_COLUMNS = {
        "name": "TEXT UNIQUE NOT NULL",
        "description": "TEXT",
        "schedule": "TEXT",
        "enabled": "INTEGER DEFAULT 1",
        "enabled_prev": "INTEGER DEFAULT NULL",
        "status": "TEXT",
        "last_run": "TIMESTAMP",
        "next_run": "TIMESTAMP",
        "last_error": "TEXT",
        "queued_count": "INTEGER NOT NULL DEFAULT 0",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "max_retries": "INTEGER NOT NULL DEFAULT 3",
        "last_attempt_at": "TIMESTAMP",
        "next_retry_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }

    for col, definition in TASK_COLUMNS.items():
        ensure_column(cursor, "tasks", col, definition)

    print("✔ Task columns verified.")

    # -------------------------------------------------
    # 2.1 Vérifier colonnes SETTINGS (migrations légères)
    # -------------------------------------------------
    ensure_column(cursor, "settings", "brand_name", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "email_history_retention_years", "INTEGER DEFAULT 2")
    ensure_column(cursor, "settings", "backup_retention_days", "INTEGER DEFAULT 30")
    ensure_column(cursor, "settings", "backup_retention_count", "INTEGER DEFAULT 10")
    ensure_column(cursor, "settings", "data_retention_years", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "skip_never_used_accounts", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "smtp_auth_method", "TEXT DEFAULT 'password'")
    ensure_column(cursor, "settings", "smtp_oauth_access_token", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "communication_language", "TEXT DEFAULT NULL")

    # Plex settings
    ensure_column(cursor, "settings", "plex_user_import_mode", "TEXT DEFAULT 'global'")



    # Auth admin
    ensure_column(cursor, "settings", "contact_email", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "admin_password_hash", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "auth_enabled", "INTEGER DEFAULT 1")
    ensure_column(cursor, "settings", "admin_totp_enabled", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "admin_totp_secret", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "admin_totp_local_trust_enabled", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "wizard_active", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "settings", "wizard_completed", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "settings", "wizard_step", "INTEGER DEFAULT 1")
    ensure_column(cursor, "settings", "wizard_state_json", "TEXT DEFAULT '{}'")
    ensure_column(cursor, "settings", "web_secure_cookies", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "web_cookie_samesite", "TEXT DEFAULT 'Lax'")
    ensure_column(cursor, "settings", "web_trust_proxy", "INTEGER DEFAULT 0")
    print("✔ Settings columns verified (brand_name).")
    # -------------------------------------------------
    # Anti brute-force login
    # -------------------------------------------------
    if not table_exists(cursor, "auth_login_attempts"):
        print("🛠 Creating table: auth_login_attempts")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL CHECK(scope IN ('ip', 'email')),
            scope_value TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            first_failed_at TIMESTAMP DEFAULT NULL,
            last_failed_at TIMESTAMP DEFAULT NULL,
            locked_until TIMESTAMP DEFAULT NULL,
            alert_sent_at TIMESTAMP DEFAULT NULL,
            alert_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scope, scope_value)
        );
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_scope "
            "ON auth_login_attempts(scope, scope_value);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_locked_until "
            "ON auth_login_attempts(locked_until);"
        )
        conn.commit()
    ensure_column(cursor, "auth_login_attempts", "alert_sent_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "auth_login_attempts", "alert_count", "INTEGER NOT NULL DEFAULT 0")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_alert_sent_at "
        "ON auth_login_attempts(alert_sent_at);"
    )
