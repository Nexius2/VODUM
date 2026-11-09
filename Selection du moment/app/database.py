import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS entries(
 id INTEGER PRIMARY KEY, plex_id TEXT NOT NULL, tmdb_id INTEGER, title TEXT NOT NULL,
 entered TEXT NOT NULL, expires TEXT NOT NULL, origin TEXT NOT NULL,
 checked TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, reason TEXT,
 removed TEXT, cooldown TEXT, event TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_active ON entries(plex_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS operations(
 id INTEGER PRIMARY KEY, action TEXT NOT NULL, plex_id TEXT NOT NULL,
 tmdb_id INTEGER, title TEXT NOT NULL, entered TEXT NOT NULL, expires TEXT NOT NULL,
 event TEXT, status TEXT NOT NULL DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS runs(
 id INTEGER PRIMARY KEY, started TEXT, finished TEXT, cleanup TEXT, population TEXT, summary TEXT);
"""


class Database:
    def __init__(self, path, dry=False):
        if not dry:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(':memory:' if dry else path)
        if dry and Path(path).exists():
            source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
            try:
                source.backup(self.db)
            finally:
                source.close()
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite : intégrité invalide')
        self.db.executescript(SCHEMA)
        self.db.commit()

    def query(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def write(self, sql, args=()):
        with self.db:
            return self.db.execute(sql, args).lastrowid

    def close(self):
        self.db.close()
