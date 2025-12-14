import sqlite3

def open_db(path=None):
    if path is None:
        path = "/appdata/database.db"

    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # PRAGMAs utiles
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    return conn
