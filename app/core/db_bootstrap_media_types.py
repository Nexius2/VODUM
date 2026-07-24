def normalize_monitoring_media_types(conn, cursor) -> None:
    print("Normalizing monitoring media_type values...")
    cursor.execute("UPDATE media_session_history SET media_type='serie' WHERE media_type='series'")
    cursor.execute("UPDATE media_session_history SET media_type='music' WHERE media_type IN ('tracks','track')")
    cursor.execute("""
        UPDATE media_session_history
        SET media_type='serie'
        WHERE media_type='video'
          AND grandparent_title IS NOT NULL
          AND TRIM(grandparent_title) <> ''
    """)
    cursor.execute("""
        UPDATE media_session_history
        SET media_type='movie'
        WHERE media_type='video'
          AND (grandparent_title IS NULL OR TRIM(grandparent_title) = '')
    """)
    cursor.execute("UPDATE media_sessions SET media_type='serie' WHERE media_type='series'")
    cursor.execute("UPDATE media_sessions SET media_type='tracks' WHERE media_type IN ('music','track')")
    cursor.execute("""
        UPDATE media_sessions
        SET media_type='serie'
        WHERE media_type='video'
          AND grandparent_title IS NOT NULL
          AND TRIM(grandparent_title) <> ''
    """)
    cursor.execute("""
        UPDATE media_sessions
        SET media_type='movie'
        WHERE media_type='video'
          AND (grandparent_title IS NULL OR TRIM(grandparent_title) = '')
    """)
    conn.commit()
    print("Monitoring media_type normalized.")
