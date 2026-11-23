"""Normalize legacy monitoring values without rescanning old history on restart."""
import time


def normalize_monitoring_media_types(conn, cursor) -> None:
    started = time.monotonic()
    cursor.execute("""CREATE TABLE IF NOT EXISTS bootstrap_data_progress (
        name TEXT PRIMARY KEY, last_row_id INTEGER NOT NULL
    )""")
    try:
        row = cursor.execute("SELECT last_row_id FROM bootstrap_data_progress WHERE name='monitoring_media_types_v1'").fetchone()
        previous = row[0] if row else 0
        maximum = cursor.execute('SELECT COALESCE(MAX(id),0) FROM media_session_history').fetchone()[0]
        changed = 0
        if maximum > previous:
            print(f"Normalizing monitoring media types (history IDs {previous + 1}–{maximum})...", flush=True)
            cursor.execute("""UPDATE media_session_history SET media_type=CASE
                WHEN media_type='series' THEN 'serie'
                WHEN media_type IN ('tracks','track') THEN 'music'
                WHEN grandparent_title IS NOT NULL AND TRIM(grandparent_title)<>'' THEN 'serie'
                ELSE 'movie' END
                WHERE id>? AND id<=? AND media_type IN ('series','tracks','track','video')""", (previous, maximum))
            changed = cursor.rowcount
        # Live sessions are small and mutable, unlike completed history rows.
        cursor.execute("""UPDATE media_sessions SET media_type=CASE
            WHEN media_type='series' THEN 'serie'
            WHEN media_type IN ('music','track') THEN 'tracks'
            WHEN grandparent_title IS NOT NULL AND TRIM(grandparent_title)<>'' THEN 'serie'
            ELSE 'movie' END WHERE media_type IN ('series','music','track','video')""")
        cursor.execute("""INSERT INTO bootstrap_data_progress(name,last_row_id)
            VALUES('monitoring_media_types_v1',?) ON CONFLICT(name)
            DO UPDATE SET last_row_id=excluded.last_row_id""", (maximum,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"Monitoring media types ready: {changed} history rows updated in {time.monotonic()-started:.2f}s (already checked history skipped).", flush=True)
