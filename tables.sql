
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

    expiration_date TIMESTAMP,
    renewal_method TEXT,
    renewal_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    notes TEXT,

    -- Per-user stream override
    max_streams_override INTEGER DEFAULT NULL,

    -- Notifications
    notifications_order_override TEXT DEFAULT NULL,

	-- Per-user expiratin date override
	expiration_date_override INTEGER DEFAULT 0,

    -- Discord
    discord_user_id TEXT DEFAULT NULL,
    discord_name TEXT DEFAULT NULL,

    -- Subscription
    subscription_template_id INTEGER DEFAULT NULL,

    -- Referral
    referrer_user_id INTEGER DEFAULT NULL,

    status TEXT DEFAULT 'expired' CHECK (status IN ('active','pre_expired','reminder','expired','invited','unfriended','suspended','unknown')),

    last_status TEXT,
    status_changed_at TIMESTAMP,

    FOREIGN KEY(referrer_user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_vodum_users_referrer_user_id
ON vodum_users(referrer_user_id);

CREATE INDEX IF NOT EXISTS idx_vodum_users_status
ON vodum_users(status);

CREATE INDEX IF NOT EXISTS idx_vodum_users_status_expiration
ON vodum_users(status, expiration_date);

CREATE INDEX IF NOT EXISTS idx_vodum_users_expiration_date
ON vodum_users(expiration_date);

CREATE INDEX IF NOT EXISTS idx_vodum_users_subscription_template
ON vodum_users(subscription_template_id);


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
CREATE INDEX IF NOT EXISTS idx_user_identities_server
ON user_identities(server_id);

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
	stored_password TEXT DEFAULT NULL,
    preferred_language TEXT DEFAULT NULL,

    type TEXT,                            -- 'plex', 'jellyfin', …

    role TEXT,
    joined_at TEXT,
    accepted_at TEXT,

    raw_json TEXT,                        -- on garde brut l'objet renvoyé par l'API

	details_json TEXT,

    FOREIGN KEY(server_id) REFERENCES servers(id),
    FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id)
);

DROP INDEX IF EXISTS uq_media_users_vodum_server;

CREATE INDEX IF NOT EXISTS idx_media_users_vodum_server
ON media_users(vodum_user_id, server_id)
WHERE vodum_user_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_media_users_provider_server_external
ON media_users(server_id, type, external_user_id)
WHERE external_user_id IS NOT NULL
  AND TRIM(external_user_id) <> '';

CREATE INDEX IF NOT EXISTS idx_media_users_server
ON media_users(server_id);

CREATE INDEX IF NOT EXISTS idx_media_users_vodum_user
ON media_users(vodum_user_id);

-----------------------------------------------------------------------
--  DATABASE SERVERS 
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT,
    server_identifier TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,

    url TEXT,
    local_url TEXT,
    public_url TEXT,
    token TEXT,

    settings_json TEXT,
    server_version TEXT,

    -- Temporary cooldown for unreachable media servers
    unavailable_since TIMESTAMP DEFAULT NULL,
    cooldown_until TIMESTAMP DEFAULT NULL,
    last_failure TEXT DEFAULT NULL,

    last_checked TIMESTAMP,
    status TEXT
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

CREATE INDEX IF NOT EXISTS idx_libraries_server
ON libraries(server_id);


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

CREATE INDEX IF NOT EXISTS idx_media_user_libraries_library
ON media_user_libraries(library_id);

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

CREATE INDEX IF NOT EXISTS idx_welcome_email_templates_server
ON welcome_email_templates(server_id);

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
    smtp_auth_method TEXT DEFAULT 'password',
    smtp_oauth_access_token TEXT DEFAULT NULL,
    email_history_retention_years INTEGER DEFAULT 2,

    disable_on_expiry INTEGER DEFAULT 0,
    delete_after_expiry_days INTEGER DEFAULT 30,
    send_reminders INTEGER DEFAULT 1,
    preavis_days INTEGER NOT NULL DEFAULT 30,
    reminder_days INTEGER NOT NULL DEFAULT 7,

    default_language TEXT DEFAULT NULL,
    communication_language TEXT DEFAULT NULL,
    timezone TEXT DEFAULT 'Europe/Paris',
    admin_email TEXT,
    contact_email TEXT,
    admin_password_hash TEXT,
    auth_enabled INTEGER DEFAULT 1,
    admin_totp_enabled INTEGER DEFAULT 0,
    admin_totp_secret TEXT,
    wizard_active INTEGER DEFAULT 1,
    wizard_completed INTEGER DEFAULT 0,
    wizard_step INTEGER DEFAULT 1,
    wizard_state_json TEXT DEFAULT '{}',

    web_secure_cookies INTEGER DEFAULT 0,
    web_cookie_samesite TEXT DEFAULT 'Lax',
    web_trust_proxy INTEGER DEFAULT 0,

    enable_cron_jobs INTEGER DEFAULT 1,
    default_expiration_days INTEGER DEFAULT 90,
    default_subscription_days INTEGER DEFAULT 90,

    maintenance_mode INTEGER DEFAULT 0,
    debug_mode INTEGER DEFAULT 0,

      backup_retention_days INTEGER DEFAULT 30,
      backup_retention_count INTEGER DEFAULT 10,
      data_retention_years INTEGER DEFAULT 0,

    brand_name TEXT DEFAULT NULL,

    -- Global notification channels order (e.g. "email,discord")
    notifications_order TEXT DEFAULT 'email',
    -- Allow per-user override of the notification order
    user_notifications_can_override INTEGER DEFAULT 0,
    -- Send policy: first successful channel OR all available channels
    notifications_send_mode TEXT DEFAULT 'first',

    -- Expiration handling mode
    expiry_mode TEXT DEFAULT 'disable',
    warn_then_disable_days INTEGER DEFAULT 7,

    -- Discord
    discord_enabled INTEGER DEFAULT 0,
    -- Legacy token (kept for backward-compat)
    discord_bot_token TEXT DEFAULT NULL,
    -- Preferred bot reference (discord_bots.id)
    discord_bot_id INTEGER DEFAULT NULL,

    mailing_enabled INTEGER DEFAULT 0,
    skip_never_used_accounts INTEGER DEFAULT 0,
	
	plex_user_import_mode TEXT DEFAULT 'global',

	-- Telemetry
	enable_anonymous_telemetry INTEGER DEFAULT 1,
	telemetry_instance_id TEXT DEFAULT NULL,
	telemetry_last_sent_at TEXT DEFAULT NULL,
	task_defaults_version INTEGER DEFAULT 0,
    stream_enforcer_boost_until TIMESTAMP DEFAULT NULL,

    usage_risk_enabled INTEGER DEFAULT 1,
    usage_risk_send_upgrade_suggestions INTEGER DEFAULT 0,
    usage_risk_send_stream_blocked_message INTEGER DEFAULT 0,
    usage_risk_min_kills_before_suggestion INTEGER DEFAULT 3,
    usage_risk_analysis_window_days INTEGER DEFAULT 30,
    usage_risk_suggestion_cooldown_days INTEGER DEFAULT 30,
    usage_risk_medium_threshold INTEGER DEFAULT 40,
    usage_risk_high_threshold INTEGER DEFAULT 75

);

-----------------------------------------------------------------------
--  AUTH LOGIN ATTEMPTS (anti brute force)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK(scope IN ('ip', 'email')),
    scope_value TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    first_failed_at TIMESTAMP DEFAULT NULL,
    last_failed_at TIMESTAMP DEFAULT NULL,
    locked_until TIMESTAMP DEFAULT NULL,
    alert_sent_at TIMESTAMP DEFAULT NULL,
    alert_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scope, scope_value)
);

CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_scope
ON auth_login_attempts(scope, scope_value);

CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_locked_until
ON auth_login_attempts(locked_until);

CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_alert_sent_at
ON auth_login_attempts(alert_sent_at);

-----------------------------------------------------------------------
--  SUBSCRIPTION TEMPLATES
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscription_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    notes TEXT,
    duration_days INTEGER DEFAULT 30,
    subscription_value REAL DEFAULT 0,
    is_default INTEGER DEFAULT 0,
    is_enabled INTEGER DEFAULT 1,
    is_lifetime INTEGER DEFAULT 0,
    policies_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_subscription_templates_name
ON subscription_templates(name);

-----------------------------------------------------------------------
--  USER REFERRAL SETTINGS
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_referral_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),

    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    reward_enabled INTEGER NOT NULL DEFAULT 1 CHECK(reward_enabled IN (0,1)),
    qualification_days INTEGER NOT NULL DEFAULT 60,
    reward_days INTEGER NOT NULL DEFAULT 60,

    allow_referrer_change_before_qualification INTEGER NOT NULL DEFAULT 1 CHECK(allow_referrer_change_before_qualification IN (0,1)),
    auto_notify_reward INTEGER NOT NULL DEFAULT 1 CHECK(auto_notify_reward IN (0,1)),

    eligible_statuses TEXT NOT NULL DEFAULT 'active',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	
	auto_expire_pending INTEGER NOT NULL DEFAULT 1,
	auto_archive_rewarded INTEGER NOT NULL DEFAULT 1,
	auto_archive_expired INTEGER NOT NULL DEFAULT 1,

	pending_expire_days INTEGER NOT NULL DEFAULT 0,
	rewarded_archive_days INTEGER NOT NULL DEFAULT 90,
	expired_archive_days INTEGER NOT NULL DEFAULT 30
);

-----------------------------------------------------------------------
--  USER REFERRALS
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    referrer_user_id INTEGER NOT NULL,
    referred_user_id INTEGER NOT NULL UNIQUE,

	status TEXT NOT NULL DEFAULT 'pending'
		CHECK(status IN (
			'pending',
			'qualified',
			'rewarded',
			'expired',
			'archived',
			'cancelled'
		)),

    referral_source TEXT DEFAULT 'manual',

    start_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    qualification_due_at TIMESTAMP,
    qualified_at TIMESTAMP DEFAULT NULL,

    qualification_days_snapshot INTEGER NOT NULL DEFAULT 60,
    reward_days_snapshot INTEGER NOT NULL DEFAULT 60,

    reward_granted_at TIMESTAMP DEFAULT NULL,
    reward_expiration_before TEXT DEFAULT NULL,
    reward_expiration_after TEXT DEFAULT NULL,
	expired_at TIMESTAMP DEFAULT NULL,
	archived_at TIMESTAMP DEFAULT NULL,

    notification_sent_at TIMESTAMP DEFAULT NULL,
    notification_template_id INTEGER DEFAULT NULL,
    last_error TEXT DEFAULT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(referrer_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
    FOREIGN KEY(referred_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
    FOREIGN KEY(notification_template_id) REFERENCES comm_templates(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_user_referrals_referrer_user_id
ON user_referrals(referrer_user_id);

CREATE INDEX IF NOT EXISTS idx_user_referrals_status
ON user_referrals(status);

CREATE INDEX IF NOT EXISTS idx_user_referrals_qualification_due_at
ON user_referrals(qualification_due_at);

-----------------------------------------------------------------------
--  USER REFERRAL EVENTS
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_referral_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    referral_id INTEGER NOT NULL,
    event_type TEXT NOT NULL
        CHECK(event_type IN (
            'created',
            'referrer_changed',
            'qualified',
            'reward_granted',
            'notification_sent',
            'cancelled'
        )),

    actor TEXT DEFAULT 'system',
    old_referrer_user_id INTEGER DEFAULT NULL,
    new_referrer_user_id INTEGER DEFAULT NULL,
    details_json TEXT DEFAULT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(referral_id) REFERENCES user_referrals(id) ON DELETE CASCADE,
    FOREIGN KEY(old_referrer_user_id) REFERENCES vodum_users(id) ON DELETE SET NULL,
    FOREIGN KEY(new_referrer_user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_user_referral_events_referral_id
ON user_referral_events(referral_id);

-----------------------------------------------------------------------
--  TASKS (scheduler)
-----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    schedule TEXT,                    -- cron-like, "0 */1 * * *", etc.
	schedule_mode TEXT DEFAULT 'cron',
	interval_seconds INTEGER DEFAULT NULL,
    enabled INTEGER DEFAULT 1,
	enabled_prev INTEGER DEFAULT NULL,

    status TEXT,                      -- idle, running, error
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    last_error TEXT,
	queued_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_attempt_at TIMESTAMP,
    next_retry_at TIMESTAMP,

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
  poster_ref_json TEXT,
  backdrop_ref_json TEXT,

  library_section_id TEXT,

  missing_count INTEGER DEFAULT 0,

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
  poster_ref_json TEXT,
  backdrop_ref_json TEXT,

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

-- Dedup key for monitoring history + tautulli imports + collector upserts
CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_tautulli_dedup
ON media_session_history (server_id, media_user_id, started_at, media_key, client_name);
CREATE INDEX IF NOT EXISTS idx_media_session_history_session_lookup
ON media_session_history (server_id, session_key, media_key, started_at)
WHERE TRIM(COALESCE(session_key,'')) <> '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_media_jobs_dedupe_active
ON media_jobs(dedupe_key)
WHERE dedupe_key IS NOT NULL AND status IN ('queued','running');

CREATE INDEX IF NOT EXISTS idx_history_server_library_stopped
ON media_session_history(server_id, library_section_id, stopped_at);
CREATE INDEX IF NOT EXISTS idx_history_library_top_played
ON media_session_history(server_id, library_section_id, media_key, started_at, stopped_at);

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
CREATE INDEX IF NOT EXISTS idx_stream_enforcement_state_server
ON stream_enforcement_state(server_id);


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
  account_username TEXT,
  ips_json TEXT,
  details_json TEXT,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY(policy_id) REFERENCES stream_policies(id) ON DELETE CASCADE,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stream_enforcements_time
ON stream_enforcements(created_at);
CREATE INDEX IF NOT EXISTS idx_stream_enforcements_server
ON stream_enforcements(server_id, created_at);
CREATE INDEX IF NOT EXISTS idx_stream_enforcements_vodum_user_created
ON stream_enforcements(vodum_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_stream_enforcements_external_user_created
ON stream_enforcements(external_user_id, created_at);


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


-----------------------------------------------------------------------
-- COMMUNICATIONS (Unified: Email + Discord)
-----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS comm_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),

  -- trigger system
  trigger_event TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked','usage_risk_upgrade_suggestion')),
  trigger_provider TEXT NOT NULL DEFAULT 'all' CHECK(trigger_provider IN ('all','plex','jellyfin')),
  expiration_change_direction TEXT NOT NULL DEFAULT 'all' CHECK(expiration_change_direction IN ('all','increase','decrease')),

  -- subscription targeting
  subscription_scope TEXT NOT NULL DEFAULT 'none' CHECK(subscription_scope IN ('none','all','specific')),
  subscription_template_id INTEGER DEFAULT NULL,

  -- expiration flow
  days_before INTEGER DEFAULT NULL,

  -- user creation / immediate event flow
  days_after INTEGER DEFAULT NULL,

  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY(subscription_template_id) REFERENCES subscription_templates(id) ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS comm_template_translations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id INTEGER NOT NULL,
  language TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(template_id, language),
  FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comm_template_translations_template
ON comm_template_translations(template_id, language);

CREATE TABLE IF NOT EXISTS app_repairs (
    key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS comm_scheduled (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id INTEGER NOT NULL,
  vodum_user_id INTEGER NOT NULL,
  provider TEXT NOT NULL CHECK(provider IN ('plex','jellyfin')),
  server_id INTEGER,
  send_at TIMESTAMP NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','error')),
  last_error TEXT,

  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 10,
  next_attempt_at TIMESTAMP DEFAULT NULL,
  last_attempt_at TIMESTAMP DEFAULT NULL,

  payload_json TEXT DEFAULT NULL,
  dedupe_key TEXT DEFAULT NULL,
  channels_sent TEXT DEFAULT NULL,
  catchup_count INTEGER NOT NULL DEFAULT 0,
  last_catchup_at TIMESTAMP DEFAULT NULL,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE,
  FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_comm_scheduled_due
ON comm_scheduled(status, send_at);

CREATE INDEX IF NOT EXISTS idx_comm_scheduled_user
ON comm_scheduled(vodum_user_id);

CREATE INDEX IF NOT EXISTS idx_comm_scheduled_retry
ON comm_scheduled(status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_comm_scheduled_catchup
ON comm_scheduled(status, catchup_count, last_catchup_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_scheduled_dedupe
ON comm_scheduled(dedupe_key);

CREATE TABLE IF NOT EXISTS comm_template_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id INTEGER NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT,
  path TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comm_template_attachments_template ON comm_template_attachments(template_id);

CREATE TABLE IF NOT EXISTS comm_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  server_id INTEGER,
  status TEXT DEFAULT 'pending',
  is_test INTEGER DEFAULT 0 CHECK(is_test IN (0,1)),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  sent_at TIMESTAMP,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS comm_campaign_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT,
  path TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comm_campaign_attachments_campaign
ON comm_campaign_attachments(campaign_id);

CREATE TABLE IF NOT EXISTS comm_campaign_targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','error')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 10,
  next_attempt_at TIMESTAMP DEFAULT NULL,
  last_attempt_at TIMESTAMP DEFAULT NULL,
  last_error TEXT,
  channels_sent TEXT DEFAULT NULL,
  dedupe_key TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE CASCADE,
  FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comm_campaign_targets_campaign
ON comm_campaign_targets(campaign_id, status);

CREATE INDEX IF NOT EXISTS idx_comm_campaign_targets_retry
ON comm_campaign_targets(status, next_attempt_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_campaign_targets_dedupe
ON comm_campaign_targets(dedupe_key);

CREATE TABLE IF NOT EXISTS usage_risk_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    vodum_user_id INTEGER NOT NULL,

    risk_level TEXT NOT NULL,
    risk_score INTEGER NOT NULL DEFAULT 0,

    current_subscription TEXT,
    suggested_subscription TEXT NOT NULL,

    first_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_notification_at TIMESTAMP DEFAULT NULL,

    cooldown_until TIMESTAMP DEFAULT NULL,

    status TEXT NOT NULL DEFAULT 'detected'
      CHECK(status IN ('detected','notified','ignored','resolved')),

    meta_json TEXT,

    FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_usage_risk_recommendations_user
ON usage_risk_recommendations(vodum_user_id, status);

CREATE INDEX IF NOT EXISTS idx_usage_risk_recommendations_cooldown
ON usage_risk_recommendations(cooldown_until);

CREATE TABLE IF NOT EXISTS comm_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN ('template','campaign')),
  template_id INTEGER,
  campaign_id INTEGER,
  user_id INTEGER,
  channel_used TEXT NOT NULL CHECK(channel_used IN ('email','discord')),
  status TEXT NOT NULL CHECK(status IN ('sent','failed')),
  error TEXT,
  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  meta_json TEXT,
  FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE SET NULL,
  FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE SET NULL,
  FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_comm_history_sent_at ON comm_history(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_comm_history_user ON comm_history(user_id, sent_at DESC);


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

-- ----------------------------
-- Monitoring snapshots (for peak streams)
-- ----------------------------
CREATE TABLE IF NOT EXISTS monitoring_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  live_sessions INTEGER NOT NULL DEFAULT 0,
  transcodes INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_monitoring_snapshots_ts
ON monitoring_snapshots(ts);



-- ----------------------------
-- Monitoring server resources (latest CPU/RAM per server)
-- ----------------------------
CREATE TABLE IF NOT EXISTS monitoring_server_resources (
  server_id INTEGER PRIMARY KEY,
  provider TEXT,
  cpu_pct REAL,
  ram_pct REAL,
  is_available INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_monitoring_server_resources_fetched_at
ON monitoring_server_resources(fetched_at);

-- ----------------------------
-- User migration foundations
-- ----------------------------
CREATE TABLE IF NOT EXISTS migration_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source_server_id INTEGER NOT NULL,
  destination_server_id INTEGER NOT NULL,
  migration_type TEXT NOT NULL,
  migration_mode TEXT NOT NULL,
  intent TEXT NOT NULL DEFAULT 'copy',
  status TEXT NOT NULL DEFAULT 'draft',
  options_json TEXT,
  library_mapping_json TEXT,
  analysis_json TEXT,
  scheduled_at TIMESTAMP,
  batch_size INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  FOREIGN KEY(source_server_id) REFERENCES servers(id) ON DELETE RESTRICT,
  FOREIGN KEY(destination_server_id) REFERENCES servers(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_migration_campaigns_status ON migration_campaigns(status, updated_at);

CREATE TABLE IF NOT EXISTS migration_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  vodum_user_id INTEGER NOT NULL,
  source_media_user_id INTEGER,
  destination_media_user_id INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',
  eligibility TEXT NOT NULL DEFAULT 'pending',
  blockers_json TEXT,
  options_json TEXT,
  source_snapshot_json TEXT,
  result_json TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  UNIQUE(campaign_id, vodum_user_id),
  FOREIGN KEY(campaign_id) REFERENCES migration_campaigns(id) ON DELETE CASCADE,
  FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
  FOREIGN KEY(source_media_user_id) REFERENCES media_users(id) ON DELETE SET NULL,
  FOREIGN KEY(destination_media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_migration_users_campaign_status ON migration_users(campaign_id, status);

CREATE TABLE IF NOT EXISTS migration_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  migration_user_id INTEGER NOT NULL,
  step_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 10,
  run_after TIMESTAMP,
  locked_by TEXT,
  locked_until TIMESTAMP,
  last_error TEXT,
  details_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  UNIQUE(migration_user_id, step_key),
  FOREIGN KEY(migration_user_id) REFERENCES migration_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_migration_steps_queue ON migration_steps(status, run_after, locked_until);

CREATE TABLE IF NOT EXISTS migration_library_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  source_library_id INTEGER NOT NULL,
  destination_library_id INTEGER,
  mapping_status TEXT NOT NULL DEFAULT 'unmapped',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(campaign_id, source_library_id, destination_library_id),
  FOREIGN KEY(campaign_id) REFERENCES migration_campaigns(id) ON DELETE CASCADE,
  FOREIGN KEY(source_library_id) REFERENCES libraries(id) ON DELETE RESTRICT,
  FOREIGN KEY(destination_library_id) REFERENCES libraries(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_migration_library_mappings_campaign ON migration_library_mappings(campaign_id, mapping_status);

