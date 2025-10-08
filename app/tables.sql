-- Table pour stocker les abonnements
CREATE TABLE IF NOT EXISTS subscription (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    subscription_type TEXT NOT NULL,
    notified BOOLEAN DEFAULT FALSE,
	start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Table pour les utilisateurs 
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT,
    last_notification TIMESTAMP,
	discord_id TEXT DEFAULT NULL,  -- ID de l'utilisateur Discord
    plex_id TEXT UNIQUE NOT NULL,              -- ID de l'utilisateur Plex
    username TEXT NOT NULL,                        -- Nom d'utilisateur Plex
	lastname TEXT,                        
	firstname TEXT,                        
    email TEXT,
	second_email TEXT,-- Email de l'utilisateur Plex
    avatar TEXT,                           -- URL de l'avatar Plex
    role TEXT DEFAULT 'user',              -- Rôle (admin/user)
    library_access TEXT,                   -- Accès aux bibliothèques (IDs séparés par des virgules)
    content_restriction TEXT,              -- Restriction de contenu (ex: "R, PG-13")
    allow_sync BOOLEAN DEFAULT FALSE,      -- Autorisation de téléchargement mobile
    allow_deletion BOOLEAN DEFAULT FALSE,  -- Peut supprimer du contenu
    allow_sharing BOOLEAN DEFAULT TRUE,    -- Peut partager du contenu
    remote_quality TEXT DEFAULT 'Auto',    -- Qualité de streaming distant
    local_quality TEXT DEFAULT 'Auto',     -- Qualité de streaming local
    audio_boost INTEGER DEFAULT 0,         -- Boost audio
    bandwidth_limit INTEGER DEFAULT NULL,  -- Limite de bande passante en Mbps
    expiration_date TIMESTAMP DEFAULT '9999-12-31',         -- Date d'expiration de l'abonnement
	notes TEXT,
	renewal_method TEXT,
	renewal_date,
	creation_date,
	is_admin INTEGER DEFAULT 0,
	unique_key TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Date d'inscription
	status TEXT CHECK (status IN ('active','pre_expired','reminder','expired','invited','unfriended','suspended','unknown')),
	last_status TEXT,
	status_changed_at DATETIME


);

-- Table pour stocker les statistiques Plex
CREATE TABLE  IF NOT EXISTS plex_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    watched_shows INTEGER DEFAULT 0,
    watched_movies INTEGER DEFAULT 0,
    last_activity TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
);

-- Table pour les commandes administratives
CREATE TABLE  IF NOT EXISTS admin_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
);

-- Table des logs du bot
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Table des accès aux commandes
CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id INTEGER UNIQUE NOT NULL,
    role TEXT NOT NULL
);

-- Table des serveurs 
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    server_id TEXT UNIQUE,
	url TEXT,
	token TEXT,
	type TEXT,
	server_status TEXT,
	tautulli_url TEXT,
	tautulli_api_key TEXT,
	tautulli_status TEXT,
    local_url TEXT,
    public_url TEXT,
	last_checked TEXT
);

-- Table des bibliothèques Plex
CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id TEXT,
    name TEXT,
    server_id TEXT,
    FOREIGN KEY(server_id) REFERENCES servers(server_id),
    UNIQUE(section_id, server_id)
);

-- Table de relation utilisateur <-> bibliothèque
CREATE TABLE IF NOT EXISTS shared_libraries (
    user_id INTEGER,
    library_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(library_id) REFERENCES libraries(id),
    PRIMARY KEY(user_id, library_id)
);

CREATE TABLE IF NOT EXISTS user_servers (
    user_id INTEGER,
    server_id TEXT,
    source TEXT,
    allow_sync INTEGER,
    allow_camera_upload INTEGER,
    allow_channels INTEGER,
    filter_movies TEXT,
    filter_television TEXT,
    filter_music TEXT,
    PRIMARY KEY(user_id, server_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(server_id) REFERENCES servers(server_id)
);


CREATE TABLE IF NOT EXISTS user_libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    library_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(library_id) REFERENCES libraries(id)
);

CREATE TABLE IF NOT EXISTS email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT UNIQUE NOT NULL,
    subject TEXT NOT NULL,
	days_before INTEGER DEFAULT 0,
    body TEXT NOT NULL
);



CREATE TABLE IF NOT EXISTS settings (
  id INTEGER PRIMARY KEY,
  discord_token TEXT,
  discord_user_id TEXT,
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
  admin_email TEXT,
  log_level TEXT DEFAULT 'info',
  timezone TEXT DEFAULT 'Europe/Paris',
  enable_cron_jobs INTEGER DEFAULT 1,
  default_expiration_days INTEGER DEFAULT 90,
  maintenance_mode INTEGER DEFAULT 0,
  debug_mode INTEGER DEFAULT 0
);



CREATE TABLE IF NOT EXISTS sent_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
	expiration_snapshot TEXT,
    date_sent TEXT
);


CREATE TABLE IF NOT EXISTS locks (
    name TEXT PRIMARY KEY,
    acquired_at TEXT
);

CREATE TABLE IF NOT EXISTS task_status (
    name TEXT PRIMARY KEY,
    last_run TEXT,
    next_run TEXT
);

CREATE TABLE IF NOT EXISTS mail_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER,
    subject TEXT,
    html_content TEXT,
	attachment_path TEXT,
    status TEXT DEFAULT 'pending',         -- pending, sending, finished, cancelled
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
    status TEXT DEFAULT 'pending',         -- pending, sending, sent, error, cancelled
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at DATETIME,
    error_message TEXT,
	email TEXT,
    FOREIGN KEY (campaign_id) REFERENCES mail_campaigns(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_server_unique ON user_servers(user_id, server_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_library_unique ON user_libraries(user_id, library_id);




