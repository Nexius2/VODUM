from __future__ import annotations


def validate_and_upgrade_core_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
):
    # -------------------------------------------------
    # 1. Vérifier que toutes les tables existent
    # -------------------------------------------------

    REQUIRED_TABLES = {
        "vodum_users": [],
        "media_users": [],
        "servers": [],
        "libraries": [],
        "media_user_libraries": [],
        "email_templates": [],
        "sent_emails": [],
        "settings": [],
        "user_identities": [],
        "media_jobs": [],
        "tautulli_import_jobs": [],
        "tasks": [],
        "migration_campaigns": [],
        "migration_users": [],
        "migration_steps": [],
        "migration_library_mappings": []
    }


    for table in REQUIRED_TABLES:
        if not table_exists(cursor, table):
            raise RuntimeError(f"âŒ ERROR: table '{table}' does not exist ! "
                               f"-> Check that tables.sql has been imported correctly.")

    ensure_column(cursor, "servers", "server_version", "TEXT DEFAULT NULL")

    # Temporary cooldown for unreachable media servers.
    # Used to avoid hammering a down server from monitoring/sync tasks.
    ensure_column(cursor, "servers", "unavailable_since", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "servers", "cooldown_until", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "servers", "last_failure", "TEXT DEFAULT NULL")
    # Jellyfin stored password (1 password per media account/server)
    ensure_column(cursor, "media_users", "stored_password", "TEXT DEFAULT NULL")
    ensure_column(cursor, "media_users", "preferred_language", "TEXT DEFAULT NULL")
    # Vodum only needs the Jellyfin admin token to replace a user's password.
    # Purge legacy plaintext passwords; new password changes also leave this NULL.
    cursor.execute(
        """
        UPDATE media_users
        SET stored_password = NULL
        WHERE stored_password IS NOT NULL
          AND TRIM(stored_password) != ''
        """
    )
    conn.commit()


    # -------------------------------------------------
    # TELEMETRY SETTINGS
    # -------------------------------------------------
    ensure_column(cursor, "settings", "enable_anonymous_telemetry", "INTEGER DEFAULT 1")
    ensure_column(cursor, "settings", "telemetry_instance_id", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "telemetry_last_sent_at", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "task_defaults_version", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "stream_enforcer_boost_until", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "settings", "usage_risk_enabled", "INTEGER DEFAULT 1")
    ensure_column(cursor, "settings", "usage_risk_send_upgrade_suggestions", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "usage_risk_send_stream_blocked_message", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "usage_risk_min_kills_before_suggestion", "INTEGER DEFAULT 3")
    ensure_column(cursor, "settings", "usage_risk_analysis_window_days", "INTEGER DEFAULT 30")
    ensure_column(cursor, "settings", "usage_risk_suggestion_cooldown_days", "INTEGER DEFAULT 30")
    ensure_column(cursor, "settings", "usage_risk_medium_threshold", "INTEGER DEFAULT 40")
    ensure_column(cursor, "settings", "usage_risk_high_threshold", "INTEGER DEFAULT 75")
    ensure_column(cursor, "settings", "subscription_plans_enabled_only", "INTEGER DEFAULT 0")
    conn.commit()
