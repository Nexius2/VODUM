def ensure_monitoring_live_schema(conn, cursor, *, table_exists) -> None:
    if not table_exists(cursor, "media_sessions"):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              server_id INTEGER NOT NULL,
              provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),
              session_key TEXT NOT NULL,
              media_user_id INTEGER,
              external_user_id TEXT,
              media_key TEXT,
              media_type TEXT,
              title TEXT,
              grandparent_title TEXT,
              parent_title TEXT,
              state TEXT,
              progress_ms INTEGER,
              duration_ms INTEGER,
              is_transcode INTEGER DEFAULT 0 CHECK (is_transcode IN (0,1)),
              bitrate INTEGER,
              video_codec TEXT,
              audio_codec TEXT,
              client_name TEXT,
              client_product TEXT,
              device TEXT,
              ip TEXT,
              started_at TIMESTAMP,
              last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              raw_json TEXT,
              UNIQUE(server_id, session_key),
              FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
              FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
            )
        """)
        conn.commit()

    if not table_exists(cursor, "media_events"):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              server_id INTEGER NOT NULL,
              provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),
              event_type TEXT NOT NULL,
              ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              session_key TEXT,
              media_user_id INTEGER,
              external_user_id TEXT,
              media_key TEXT,
              media_type TEXT,
              title TEXT,
              payload_json TEXT,
              FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
              FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
            )
        """)
        conn.commit()

    cursor.execute("""
        DELETE FROM media_sessions
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM media_sessions
            GROUP BY server_id, session_key
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_media_sessions_server_session
        ON media_sessions(server_id, session_key)
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_sessions_last_seen ON media_sessions(server_id, last_seen_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_sessions_user ON media_sessions(media_user_id, last_seen_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_events_ts ON media_events(server_id, ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_events_user_ts ON media_events(media_user_id, ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_events_type_ts ON media_events(event_type, ts)")
    conn.commit()
    print("Monitoring tables verified (media_sessions, media_events).")
