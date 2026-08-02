import sqlite3


def ensure_monitoring_history_schema(conn, cursor, *, table_exists, ensure_column) -> None:
    if not table_exists(cursor, "media_session_history"):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_session_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              server_id INTEGER NOT NULL,
              provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),
              session_key TEXT,
              media_key TEXT,
              external_user_id TEXT,
              media_user_id INTEGER,
              media_type TEXT,
              title TEXT,
              grandparent_title TEXT,
              parent_title TEXT,
              started_at TIMESTAMP NOT NULL,
              stopped_at TIMESTAMP NOT NULL,
              duration_ms INTEGER NOT NULL DEFAULT 0,
              watch_ms INTEGER NOT NULL DEFAULT 0,
              peak_bitrate INTEGER,
              was_transcode INTEGER NOT NULL DEFAULT 0,
              client_name TEXT,
              client_product TEXT,
              device TEXT,
              ip TEXT,
              raw_json TEXT,
              FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
              FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
            )
        """)
    else:
        ensure_column(cursor, "media_session_history", "peak_bitrate", "INTEGER")
        ensure_column(cursor, "media_session_history", "was_transcode", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(cursor, "media_session_history", "device", "TEXT")
        ensure_column(cursor, "media_session_history", "raw_json", "TEXT")
        ensure_column(cursor, "media_session_history", "ip", "TEXT")
        ensure_column(cursor, "media_session_history", "client_product", "TEXT")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_time ON media_session_history(started_at, stopped_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_user_time ON media_session_history(media_user_id, started_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_media_time ON media_session_history(media_key, started_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_stopped_media_type ON media_session_history(stopped_at, media_type)")

    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_tautulli_dedup
            ON media_session_history (server_id, media_user_id, started_at, media_key, client_name)
        """)
    except sqlite3.IntegrityError:
        print("Detected duplicates in media_session_history; deduplicating before index creation")
        cursor.execute("""
            DELETE FROM media_session_history
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM media_session_history
                GROUP BY server_id, media_user_id, started_at, media_key, client_name
            )
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_tautulli_dedup
            ON media_session_history (server_id, media_user_id, started_at, media_key, client_name)
        """)

    conn.commit()
    print("Monitoring history table verified (media_session_history).")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_daily_stats (
          day TEXT PRIMARY KEY,
          sessions INTEGER NOT NULL DEFAULT 0,
          watch_ms INTEGER NOT NULL DEFAULT 0,
          active_users INTEGER NOT NULL DEFAULT 0,
          viewer_keys_json TEXT NOT NULL DEFAULT '[]',
          top_users_json TEXT NOT NULL DEFAULT '[]',
          top_media_json TEXT NOT NULL DEFAULT '[]',
          source_max_id INTEGER NOT NULL DEFAULT 0,
          computed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_daily_stats_computed ON monitoring_daily_stats(computed_at)")
    conn.commit()
    print("Monitoring daily aggregate table verified.")
