import sqlite3

def open_db(path=None):
    # DEFAULT fallback si aucun chemin n'est donné
    if path is None:
        path = "/appdata/database.db"   # même valeur que app.config["DATABASE"]
    
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn
