def ensure_application_query_indexes(conn, cursor) -> None:
    cursor.execute("DROP INDEX IF EXISTS uq_media_users_vodum_server")
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_vodum_users_status ON vodum_users(status)",
        "CREATE INDEX IF NOT EXISTS idx_vodum_users_status_expiration ON vodum_users(status, expiration_date)",
        "CREATE INDEX IF NOT EXISTS idx_vodum_users_expiration_date ON vodum_users(expiration_date)",
        "CREATE INDEX IF NOT EXISTS idx_vodum_users_subscription_template ON vodum_users(subscription_template_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_referrals_status_start ON user_referrals(status, start_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_media_users_vodum_server ON media_users(vodum_user_id, server_id) WHERE vodum_user_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_media_users_server ON media_users(server_id)",
        "CREATE INDEX IF NOT EXISTS idx_media_users_vodum_user ON media_users(vodum_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_libraries_server ON libraries(server_id)",
        "CREATE INDEX IF NOT EXISTS idx_media_user_libraries_library ON media_user_libraries(library_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_identities_server ON user_identities(server_id)",
        "CREATE INDEX IF NOT EXISTS idx_welcome_email_templates_server ON welcome_email_templates(server_id)",
        "CREATE INDEX IF NOT EXISTS idx_stream_enforcement_state_server ON stream_enforcement_state(server_id)",
        "CREATE INDEX IF NOT EXISTS idx_stream_enforcements_server ON stream_enforcements(server_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_history_server_library_stopped ON media_session_history(server_id, library_section_id, stopped_at)",
        "CREATE INDEX IF NOT EXISTS idx_history_library_top_played ON media_session_history(server_id, library_section_id, media_key, started_at, stopped_at)",
    )
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    print("Application query indexes verified.")
