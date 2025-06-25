import sqlite3
from datetime import datetime, timedelta
from config import DATABASE_PATH  # adapte ce chemin si nécessaire

def update_task_status(task_name, interval_seconds=None):
    now = datetime.now()
    next_run = (now + timedelta(seconds=interval_seconds)).strftime("%Y-%m-%d %H:%M:%S") if interval_seconds else None

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO task_status (name, last_run, next_run)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_run = excluded.last_run,
            next_run = excluded.next_run
    """, (task_name, now.strftime("%Y-%m-%d %H:%M:%S"), next_run))
    conn.commit()
    conn.close()
