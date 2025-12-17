import sqlite3
import sys

DB_PATH = sys.argv[1]
MIGRATION_VERSION = "20251215_add_jellyfin_id_and_nullable_plex_id"

SQL = """
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

-- =================================================
-- Nettoyage des triggers éventuels sur users
-- (évite les références fantômes vers users_old)
-- =================================================
DROP TRIGGER IF EXISTS users_after_insert;
DROP TRIGGER IF EXISTS users_after_update;
DROP TRIGGER IF EXISTS users_after_delete;

-- =================================================
-- USERS
-- =================================================
ALTER TABLE users RENAME TO users_old;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    plex_id TEXT,
    jellyfin_id TEXT UNIQUE,

    username TEXT NOT NULL,

    firstname TEXT,
    lastname TEXT,
    email TEXT,
    second_email TEXT,
    avatar TEXT,

    plex_role TEXT DEFAULT 'unknown',
    notes TEXT,

    protected INTEGER DEFAULT 0,
    home INTEGER DEFAULT 0,
    restricted INTEGER DEFAULT 0,

    joined_at TEXT,
    accepted_at TEXT,

    subscription_active INTEGER DEFAULT 0,
    subscription_status TEXT,
    subscription_plan TEXT,

    expiration_date TIMESTAMP DEFAULT NULL,
    renewal_method TEXT,
    renewal_date TEXT,
    creation_date TEXT,

    status TEXT DEFAULT 'expired'
        CHECK (status IN ('active','pre_expired','reminder','expired')),

    last_status TEXT,
    status_changed_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (
    id,
    plex_id,
    jellyfin_id,
    username,
    firstname,
    lastname,
    email,
    second_email,
    avatar,
    plex_role,
    notes,
    protected,
    home,
    restricted,
    joined_at,
    accepted_at,
    subscription_active,
    subscription_status,
    subscription_plan,
    expiration_date,
    renewal_method,
    renewal_date,
    creation_date,
    status,
    last_status,
    status_changed_at,
    created_at
)
SELECT
    id,
    plex_id,
    NULL,
    username,
    firstname,
    lastname,
    email,
    second_email,
    avatar,
    plex_role,
    notes,
    protected,
    home,
    restricted,
    joined_at,
    accepted_at,
    subscription_active,
    subscription_status,
    subscription_plan,
    expiration_date,
    renewal_method,
    renewal_date,
    creation_date,
    status,
    last_status,
    status_changed_at,
    created_at
FROM users_old;

DROP TABLE users_old;

INSERT INTO schema_migrations (version)
VALUES ('20251215_add_jellyfin_id_and_nullable_plex_id');

COMMIT;
PRAGMA foreign_keys=ON;
"""

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute(
    "SELECT 1 FROM schema_migrations WHERE version = ?",
    (MIGRATION_VERSION,)
)

if cur.fetchone():
    print(f"[MIGRATION] {MIGRATION_VERSION} déjà appliquée")
    conn.close()
    sys.exit(0)

print(f"[MIGRATION] Application de {MIGRATION_VERSION}")
cur.executescript(SQL)
conn.commit()
conn.close()

print(f"[MIGRATION] {MIGRATION_VERSION} terminée avec succès")
