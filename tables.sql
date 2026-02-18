
-----------------------------------------------------------------------
--  TABLE VODUM USERS 
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vodum_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    username TEXT,
    firstname TEXT,
    lastname TEXT,
    email TEXT,
    second_email TEXT,
    --avatar TEXT,

    expiration_date TIMESTAMP,
    renewal_method TEXT,
    renewal_date TEXT,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	
    notes TEXT,

    -- Notifications channel order override for this user (optional)
    notifications_order_override TEXT DEFAULT NULL,


	status TEXT DEFAULT 'expired' CHECK (status IN ('active','pre_expired','reminder','expired','invited','unfriended','suspended','unknown')),
	
	last_status TEXT,
    status_changed_at TIMESTAMP
);


-----------------------------------------------------------------------
--  USERS Identities
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    vodum_user_id INTEGER NOT NULL,

    type TEXT NOT NULL,                 -- 'plex', 'jellyfin', ...
    server_id INTEGER,                  -- NULL pour Plex (ID global plex.tv), NON-NULL pour providers server-scoped
    external_user_id TEXT NOT NULL,     -- id natif (plex_id, jellyfin_user_id, ...)

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(type, server_id, external_user_id),

    FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_identities_vodum
ON user_identities(vodum_user_id);


-----------------------------------------------------------------------
--  TABLE USERS (media servers only)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_users (
	id INTEGER PRIMARY KEY AUTOINCREMENT,

    server_id INTEGER NOT NULL,           -- sur quel serveur existe ce compte
    vodum_user_id INTEGER,                -- lien vers vodum_users (toujours rempli chez toi)

    external_user_id TEXT,                -- id natif Plex/Jellyfin
    username TEXT NOT NULL,
    email TEXT,
    avatar TEXT,

    type TEXT,                            -- 'plex', 'jellyfin', …

    role TEXT,
    joined_at TEXT,
    accepted_at TEXT,

    raw_json TEXT,                        -- on garde brut l'objet renvoyé par l'API

	details_json TEXT,

    FOREIGN KEY(server_id) REFERENCES servers(id),
    FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id)
);


-----------------------------------------------------------------------
--  DATABASE SERVERS 
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT,
    server_identifier TEXT UNIQUE NOT NULL,      --  machineIdentifier
	type TEXT NOT NULL,              -- plex / jellyfin / autre

    url TEXT,
    local_url TEXT,
    public_url TEXT,
    token TEXT,

	settings_json TEXT,              -- pour les trucs spécifiques
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
	item_count INTEGER,
    UNIQUE(server_id, section_id),
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);




-----------------------------------------------------------------------
--  ACCESS : USER ↔ LIBRARY
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_user_libraries (
    media_user_id INTEGER NOT NULL,
    library_id INTEGER NOT NULL,

    PRIMARY KEY(media_user_id, library_id),

    FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE CASCADE, 
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
--  WELCOME EMAIL TEMPLATES (per provider / optional per server)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS welcome_email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),
    server_id INTEGER NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(provider, server_id),
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
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
    FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
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
	email_history_retention_years INTEGER DEFAULT 2,

    disable_on_expiry INTEGER DEFAULT 0,
    delete_after_expiry_days INTEGER DEFAULT 30,
    send_reminders INTEGER DEFAULT 1,
	preavis_days INTEGER NOT NULL DEFAULT 30,
	reminder_days INTEGER NOT NULL DEFAULT 7,

    default_language TEXT DEFAULT NULL,
    timezone TEXT DEFAULT 'Europe/Paris',
    admin_email TEXT,
	admin_password_hash TEXT,
    auth_enabled INTEGER DEFAULT 1,


    enable_cron_jobs INTEGER DEFAULT 1,
    default_expiration_days INTEGER DEFAULT 90,
	default_subscription_days INTEGER DEFAULT 90,

    maintenance_mode INTEGER DEFAULT 0,
    debug_mode INTEGER DEFAULT 0,
	
	backup_retention_days INTEGER DEFAULT 30,
	data_retention_years INTEGER DEFAULT 0,

	
	brand_name TEXT DEFAULT NULL,
	

    -- Global notification channels order (e.g. "email,discord")
    notifications_order TEXT DEFAULT 'email',
    -- Allow per-user override of the notification order
    user_notifications_can_override INTEGER DEFAULT 0,

	
    -- Discord
    discord_enabled INTEGER DEFAULT 0,
    -- Legacy token (kept for backward-compat)
    discord_bot_token TEXT DEFAULT NULL,
    -- Preferred bot reference (discord_bots.id)
    discord_bot_id INTEGER DEFAULT NULL,

    mailing_enabled INTEGER DEFAULT 0

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
	enabled_prev INTEGER DEFAULT NULL,

    status TEXT,                      -- idle, running, error
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    last_error TEXT,
	queued_count INTEGER NOT NULL DEFAULT 0,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- MEDIA JOBS (queue générique Plex/Jellyfin/Autre)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Cible du job
    provider TEXT NOT NULL CHECK (provider IN ('plex', 'jellyfin')),   -- extensible plus tard
    action   TEXT NOT NULL CHECK (action IN ('grant', 'revoke', 'sync', 'refresh')),

    -- Références CANONIQUES (internes)
    vodum_user_id INTEGER,      -- NULL si job global (ex: sync all users)
    server_id     INTEGER,      -- souvent NOT NULL ; peut être NULL si provider global (rare)
    library_id    INTEGER,      -- NULL = toutes les libs concernées

    -- Données libres (options, liste de sections, flags, etc.)
    payload_json  TEXT,

    -- Statut (remplace l’ancien couple processed/success dans la logique moderne)
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','success','error','canceled')),

    -- Priorité (plus petit = plus prioritaire)
    priority INTEGER NOT NULL DEFAULT 100,

    -- Backoff / planification (job exécutable après cette date)
    run_after TIMESTAMP,

    -- Lease / lock (anti double-execution multi-workers)
    locked_by TEXT,
    locked_until TIMESTAMP,

    -- Tentatives / erreurs
    attempts   INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 10,
    last_error TEXT,

    -- Champs legacy (tu peux les garder pour compat / UI existante)
    processed INTEGER NOT NULL DEFAULT 0 CHECK (processed IN (0, 1)),
    success   INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0, 1)),

    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    executed_at  TIMESTAMP,

    -- Optionnel mais très pratique : empêcher certains doublons en file
    -- Exemple: "plex:sync:server=1:user=12" ou "monitor:refresh:server=12"
    dedupe_key TEXT,

    FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
    FOREIGN KEY(library_id) REFERENCES libraries(id) ON DELETE CASCADE
);


-- Indexes utiles (queue scalable)
CREATE INDEX IF NOT EXISTS idx_media_jobs_pick
ON media_jobs(status, run_after, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_media_jobs_user
ON media_jobs(vodum_user_id);

CREATE INDEX IF NOT EXISTS idx_media_jobs_server
ON media_jobs(server_id);

CREATE INDEX IF NOT EXISTS idx_media_jobs_server_action
ON media_jobs(server_id, provider, action, status);




-- ---------------------------------------------------------------------
-- Schema versioning (source de vérité)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER NOT NULL,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(version),
  UNIQUE(name)
);

-- Version courante du schéma (1 ligne)
CREATE TABLE IF NOT EXISTS schema_version (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);

-- Initialisation version V2 (idempotent)
INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 2);

-- (optionnel mais utile) journaliser l'init si pas déjà présent
INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (2, 'init_v2');

-- ---------------------------------------------------------------------
-- historique des gifts 
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscription_gift_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  target_type TEXT NOT NULL,            -- 'all' | 'server'
  target_server_id INTEGER NULL,

  days_added INTEGER NOT NULL,
  reason TEXT NULL,

  users_updated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subscription_gift_run_users (
  run_id INTEGER NOT NULL,
  vodum_user_id INTEGER NOT NULL,

  PRIMARY KEY (run_id, vodum_user_id)
);


-- ------------------------------------------------------------
-- MONITORING (sessions live)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  server_id INTEGER NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

  session_key TEXT NOT NULL,                  -- id session natif (plex session key / jellyfin id)
  media_user_id INTEGER,                      -- FK media_users si résolu
  external_user_id TEXT,                      -- fallback si pas résolu

  media_key TEXT,                             -- ratingKey (plex) / itemId (jellyfin) si dispo
  media_type TEXT,                            -- movie/episode/track/unknown
  title TEXT,
  grandparent_title TEXT,                     -- série pour episode, album pour track
  parent_title TEXT,                          -- saison pour episode

  state TEXT,
  progress_ms INTEGER,
  duration_ms INTEGER,

  is_transcode INTEGER NOT NULL DEFAULT 0 CHECK (is_transcode IN (0,1)),
  bitrate INTEGER,
  video_codec TEXT,
  audio_codec TEXT,

  client_name TEXT,
  client_product TEXT,
  device TEXT,
  ip TEXT,

  started_at TIMESTAMP,
  last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  raw_json TEXT,

  library_section_id TEXT,

  UNIQUE(server_id, session_key),

  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
  FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_media_sessions_last_seen
ON media_sessions(server_id, last_seen_at);

CREATE INDEX IF NOT EXISTS idx_media_sessions_user
ON media_sessions(media_user_id, last_seen_at);


-- ------------------------------------------------------------
-- MONITORING (events)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  server_id INTEGER NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

  event_type TEXT NOT NULL,                   -- start/stop/pause/resume/heartbeat/update
  ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  session_key TEXT,
  media_user_id INTEGER,
  external_user_id TEXT,

  media_key TEXT,
  media_type TEXT,
  title TEXT,

  payload_json TEXT,

  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
  FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_media_events_ts
ON media_events(server_id, ts);

CREATE INDEX IF NOT EXISTS idx_media_events_user_ts
ON media_events(media_user_id, ts);

CREATE INDEX IF NOT EXISTS idx_media_events_type_ts
ON media_events(event_type, ts);


-- ------------------------------------------------------------
-- MONITORING (history / agrégations)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_session_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  server_id INTEGER NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

  session_key TEXT,
  media_key TEXT,
  external_user_id TEXT,

  media_user_id INTEGER,

  media_type TEXT,               -- movie/episode/track/unknown
  title TEXT,
  grandparent_title TEXT,
  parent_title TEXT,

  started_at TIMESTAMP NOT NULL,
  stopped_at TIMESTAMP NOT NULL,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  watch_ms INTEGER NOT NULL DEFAULT 0,
  peak_bitrate INTEGER,
  was_transcode INTEGER NOT NULL DEFAULT 0 CHECK (was_transcode IN (0,1)),

  client_name TEXT,
  client_product TEXT,
  device TEXT,
  ip TEXT,

  raw_json TEXT,

  library_section_id TEXT,

  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
  FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_msh_time
ON media_session_history(started_at, stopped_at);

CREATE INDEX IF NOT EXISTS idx_msh_user_time
ON media_session_history(media_user_id, started_at);

CREATE INDEX IF NOT EXISTS idx_msh_media_time
ON media_session_history(media_key, started_at);

CREATE INDEX IF NOT EXISTS idx_hist_user_stopped ON media_session_history(media_user_id, stopped_at);
CREATE INDEX IF NOT EXISTS idx_hist_server_stopped ON media_session_history(server_id, stopped_at);


CREATE UNIQUE INDEX IF NOT EXISTS uq_media_jobs_dedupe_active
ON media_jobs(dedupe_key)
WHERE dedupe_key IS NOT NULL AND status IN ('queued','running');

CREATE INDEX IF NOT EXISTS idx_history_server_library_stopped
ON media_session_history(server_id, library_section_id, stopped_at);

-----------------------------------------------------------------------
-- STREAM POLICIES (enforcement)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stream_policies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  -- scope : global, server, user
  scope_type TEXT NOT NULL CHECK (scope_type IN ('global','server','user')),
  scope_id INTEGER, -- NULL pour global ; servers.id pour server ; vodum_users.id pour user

  provider TEXT NULL CHECK (provider IN ('plex','jellyfin')), -- NULL => both
  server_id INTEGER NULL,   -- optionnel (si tu veux cibler un serveur précis)
  is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
  priority INTEGER NOT NULL DEFAULT 100,

  rule_type TEXT NOT NULL CHECK (rule_type IN (
    'max_streams_per_user',
	'max_streams_per_ip',
	'max_ips_per_user',
    'max_transcodes_global',
    'ban_4k_transcode',
    'max_bitrate_kbps',
    'device_allowlist'
  )),

  rule_value_json TEXT NOT NULL, -- JSON (valeurs de règle + options)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stream_policies_scope
ON stream_policies(scope_type, scope_id);

CREATE INDEX IF NOT EXISTS idx_stream_policies_enabled
ON stream_policies(is_enabled, priority);


-----------------------------------------------------------------------
-- STREAM ENFORCEMENT STATE (warn -> recheck -> kill)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stream_enforcement_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  policy_id INTEGER NOT NULL,
  server_id INTEGER NOT NULL,

  actor_key TEXT NOT NULL,       -- ✅ clé normalisée (vodum:ID ou ext:XYZ)
  vodum_user_id INTEGER,
  external_user_id TEXT,

  first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  warned_at TIMESTAMP,
  killed_at TIMESTAMP,
  last_reason TEXT,

  UNIQUE(policy_id, server_id, actor_key),

  FOREIGN KEY(policy_id) REFERENCES stream_policies(id) ON DELETE CASCADE,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stream_state_actor
ON stream_enforcement_state(actor_key);



-----------------------------------------------------------------------
-- STREAM ENFORCEMENT LOG (audit)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stream_enforcements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  policy_id INTEGER NOT NULL,
  server_id INTEGER NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

  session_key TEXT,
  vodum_user_id INTEGER,
  external_user_id TEXT,
  action TEXT NOT NULL CHECK (action IN ('warn','kill')),
  reason TEXT,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY(policy_id) REFERENCES stream_policies(id) ON DELETE CASCADE,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stream_enforcements_time
ON stream_enforcements(created_at);



-----------------------------------------------------------------------


-----------------------------------------------------------------------
-- DISCORD (DM notifications + campaigns)
-----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS discord_bots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  token TEXT DEFAULT NULL,
  bot_user_id TEXT DEFAULT NULL,
  bot_username TEXT DEFAULT NULL,
  bot_type TEXT NOT NULL DEFAULT 'custom' CHECK(bot_type IN ('custom','vodum')),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_discord_bots_type ON discord_bots(bot_type);

CREATE TABLE IF NOT EXISTS discord_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT UNIQUE NOT NULL CHECK(type IN ('preavis','relance','fin')),
  title TEXT,
  body TEXT
);

CREATE TABLE IF NOT EXISTS sent_discord (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  template_type TEXT NOT NULL,
  expiration_date TEXT,
  sent_at INTEGER,
  UNIQUE(user_id, template_type, expiration_date),
  FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discord_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  server_id INTEGER,
  is_test INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending','sent','failed')),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  sent_at TIMESTAMP,
  error TEXT,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tautulli_import_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER,
    file_path TEXT NOT NULL,
    keep_all_users INTEGER NOT NULL DEFAULT 0,
    keep_all_libraries INTEGER NOT NULL DEFAULT 0,
    import_only_available_libraries INTEGER NOT NULL DEFAULT 1,
    target_server_id INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('queued','running','success','error')),
    stats_json TEXT,
    last_error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    finished_at DATETIME
);


CREATE INDEX IF NOT EXISTS idx_tautulli_import_jobs_status ON tautulli_import_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tautulli_import_jobs_server ON tautulli_import_jobs(server_id);
