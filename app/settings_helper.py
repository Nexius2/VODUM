import sqlite3
from config import DATABASE_PATH


def get_settings():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}
