-----------------------------------------------------------------------
--  TABLE USERS (Plex only)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    plex_id TEXT UNIQUE,
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

    status TEXT DEFAULT 'expired' CHECK (status IN ('active','pre_expired','reminder','expired')),

    last_status TEXT,
    status_changed_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-----------------------------------------------------------------------
--  DATABASE SERVERS 
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT,
    server_identifier TEXT UNIQUE NOT NULL,      --  machineIdentifier
	type TEXT,

    url TEXT,
    local_url TEXT,
    public_url TEXT,
    token TEXT,

    -- Tautulli (optional)
    tautulli_url TEXT,
    tautulli_api_key TEXT,

    last_checked TIMESTAMP,
    status TEXT                         -- up/down/unknown
);

-----------------------------------------------------------------------
--  LIBRARIES
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    section_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    UNIQUE(server_id, section_id),
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

-----------------------------------------------------------------------
--  ACCESS : USER ↔ SERVER
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_servers (
    user_id INTEGER NOT NULL,
    server_id INTEGER NOT NULL,

    owned INTEGER DEFAULT 0,
    all_libraries INTEGER DEFAULT 0,
    num_libraries INTEGER DEFAULT 0,
    pending INTEGER DEFAULT 0,
    last_seen_at TEXT,

    allow_sync INTEGER DEFAULT 0,
    allow_camera_upload INTEGER DEFAULT 0,
    allow_channels INTEGER DEFAULT 0,
    allow_tuners INTEGER DEFAULT 0,
    allow_subtitle_admin INTEGER DEFAULT 0,

    filter_all TEXT,
    filter_movies TEXT,
    filter_music TEXT,
    filter_photos TEXT,
    filter_television TEXT,
    recommendations_playlist_id TEXT,

    source TEXT DEFAULT 'plex_api',

    PRIMARY KEY (user_id, server_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);


-----------------------------------------------------------------------
--  ACCESS : USER ↔ LIBRARY
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shared_libraries (
    user_id INTEGER NOT NULL,
    library_id INTEGER NOT NULL,
    PRIMARY KEY(user_id, library_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(library_id) REFERENCES libraries(id) ON DELETE CASCADE
);

-----------------------------------------------------------------------
--  EMAIL TEMPLATES
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT UNIQUE NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    days_before INTEGER DEFAULT 0,
	default_subject TEXT,
	default_body TEXT

);


-----------------------------------------------------------------------
--  SENT EMAILS HISTORY
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sent_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id INTEGER NOT NULL,
    template_type TEXT NOT NULL,          -- preavis / relance / fin
    expiration_date DATE NOT NULL,        -- cycle d’abonnement

    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_id, template_type, expiration_date),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);


-----------------------------------------------------------------------
--  MAIL CAMPAIGNS (mass mailing)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mail_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    server_id INTEGER,              -- NULL = tous les serveurs
    status TEXT DEFAULT 'pending',  -- pending / sending / finished / cancelled / error
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
	is_test INTEGER DEFAULT 0,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
);



-----------------------------------------------------------------------
--  SETTINGS
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY,
    mail_from TEXT,
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_tls INTEGER,
    smtp_user TEXT,
    smtp_pass TEXT,

    disable_on_expiry INTEGER DEFAULT 0,
    delete_after_expiry_days INTEGER DEFAULT 30,
    send_reminders INTEGER DEFAULT 1,

    default_language TEXT DEFAULT 'en',
    timezone TEXT DEFAULT 'Europe/Paris',
    admin_email TEXT,

    enable_cron_jobs INTEGER DEFAULT 1,
    default_expiration_days INTEGER DEFAULT 90,
	default_subscription_days INTEGER DEFAULT 90,

    maintenance_mode INTEGER DEFAULT 0,
    debug_mode INTEGER DEFAULT 0,
	
	backup_retention_days INTEGER DEFAULT 30,
	
	mailing_enabled INTEGER DEFAULT 0

);

-----------------------------------------------------------------------
--  LOGS (multi-critères)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT,              -- INFO / WARNING / ERROR
    category TEXT,           -- sync_plex, emails, db, server_check...
    message TEXT NOT NULL,
    details TEXT,            -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-----------------------------------------------------------------------
--  TASKS (scheduler)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    schedule TEXT,                    -- cron-like, "0 */1 * * *", etc.
    enabled INTEGER DEFAULT 1,

    status TEXT,                      -- idle, running, error
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    last_error TEXT,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-----------------------------------------------------------------------
--  PLEX JOBS (file d'attente pour les mises à jour d'accès)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plex_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,          -- 'grant' / 'revoke' / 'sync' ...
    user_id INTEGER,               -- NULL = tous les users concernés
    server_id INTEGER,             -- NULL possible pour certains jobs globaux
    library_id INTEGER,            -- NULL = toutes les libs du serveur
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed INTEGER DEFAULT 0,   -- 0 = en attente, 1 = traité

    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
    FOREIGN KEY(library_id) REFERENCES libraries(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
