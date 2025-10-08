


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

-- ======================================================================
-- Mailing campaigns & queue (bulk emails) - 2025-10-06
-- Create tables if they do not exist
-- ======================================================================


CREATE TABLE IF NOT EXISTS mail_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER,
  subject TEXT,
  html_content TEXT,
  attachment_path TEXT,
  status TEXT DEFAULT 'pending',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  finished_at DATETIME
);

CREATE TABLE IF NOT EXISTS mail_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  server_id INTEGER,
  user_id INTEGER,
  subject TEXT,
  html_content TEXT,
  status TEXT DEFAULT 'pending',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  sent_at DATETIME,
  error_message TEXT,
  FOREIGN KEY (campaign_id) REFERENCES mail_campaigns(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_queue_unique
  ON mail_queue(campaign_id, user_id);
