


-- Migration : mise à jour des statuts utilisateurs (ajout de reminder et unknown)
-- Migration : mise à jour de la contrainte CHECK sur la colonne status
-- Ajout des statuts 'reminder' et 'unknown'
PRAGMA foreign_keys=off;

ALTER TABLE users RENAME TO users_old;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plex_id TEXT,
    username TEXT,
    email TEXT,
    avatar TEXT,
    is_admin INTEGER DEFAULT 0,
    firstname TEXT,
    lastname TEXT,
    second_email TEXT,
    expiration_date TEXT,
    last_status TEXT,
    status TEXT CHECK (
        status IN ('active','pre_expired','reminder','expired','invited','unfriended','suspended','unknown')
    ),
    status_changed_at TEXT
);

INSERT INTO users (
    id, plex_id, username, email, avatar, is_admin,
    firstname, lastname, second_email,
    expiration_date, last_status, status, status_changed_at
)
SELECT
    id, plex_id, username, email, avatar, is_admin,
    firstname, lastname, second_email,
    expiration_date, last_status, status, status_changed_at
FROM users_old;

DROP TABLE users_old;

PRAGMA foreign_keys=on;
