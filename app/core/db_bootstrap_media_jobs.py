def upgrade_media_jobs_schema(conn, cursor, *, table_exists, column_exists, ensure_column) -> None:
    if table_exists(cursor, "media_jobs"):
        ensure_column(cursor, "media_jobs", "status", "TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','success','error','canceled'))")
        ensure_column(cursor, "media_jobs", "priority", "INTEGER NOT NULL DEFAULT 100")
        ensure_column(cursor, "media_jobs", "run_after", "TIMESTAMP")
        ensure_column(cursor, "media_jobs", "locked_by", "TEXT")
        ensure_column(cursor, "media_jobs", "locked_until", "TIMESTAMP")
        ensure_column(cursor, "media_jobs", "max_attempts", "INTEGER NOT NULL DEFAULT 10")
        ensure_column(cursor, "media_jobs", "processed", "INTEGER NOT NULL DEFAULT 0 CHECK (processed IN (0,1))")
        ensure_column(cursor, "media_jobs", "success", "INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0,1))")
        ensure_column(cursor, "media_jobs", "attempts", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(cursor, "media_jobs", "dedupe_key", "TEXT")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_user_stopped ON media_session_history (media_user_id, stopped_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_server_stopped ON media_session_history (server_id, stopped_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_server_library_stopped ON media_session_history (server_id, library_section_id, stopped_at)")
        cursor.execute("DROP INDEX IF EXISTS uq_media_session_history_session")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_media_session_history_session_lookup
            ON media_session_history (server_id, session_key, media_key, started_at)
            WHERE TRIM(COALESCE(session_key,'')) <> ''
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_users_vodum_user ON media_users (vodum_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_jobs_pick ON media_jobs(status, run_after, priority, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_jobs_user ON media_jobs(vodum_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_jobs_server ON media_jobs(server_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_jobs_server_action ON media_jobs(server_id, provider, action, status)")
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_media_jobs_dedupe_active
            ON media_jobs(dedupe_key)
            WHERE dedupe_key IS NOT NULL AND status IN ('queued','running')
        """)
        conn.commit()
        print("Media jobs queue columns + indexes verified.")
    else:
        print("media_jobs table not found; skipping media_jobs upgrade.")

    additions = (
        ("libraries", "item_count", "INTEGER"),
        ("media_sessions", "library_section_id", "TEXT"),
        ("media_sessions", "poster_ref_json", "TEXT"),
        ("media_sessions", "backdrop_ref_json", "TEXT"),
        ("media_sessions", "missing_count", "INTEGER DEFAULT 0"),
        ("media_session_history", "library_section_id", "TEXT"),
        ("media_session_history", "poster_ref_json", "TEXT"),
        ("media_session_history", "backdrop_ref_json", "TEXT"),
    )
    for table, column, definition in additions:
        if table_exists(cursor, table) and not column_exists(cursor, table, column):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()
            print(f"{table}.{column} added")
