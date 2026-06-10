import sqlite3
import os

DB_PATH = os.environ.get("DATABASE_PATH", "/appdata/database.db")

# ---------------------------------------------------------
# Utility: checks
# ---------------------------------------------------------

def table_exists(cursor, table):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def ensure_column(cursor, table, column, definition):
    if not column_exists(cursor, table, column):
        print(f"🛠 Ajout de la colonne manquante : {table}.{column}")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def ensure_row(cursor, table, where_clause, values):
    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}", values)
    if cursor.fetchone()[0] == 0:
        fields = ", ".join(values.keys())
        placeholders = ", ".join(["?"] * len(values))
        cursor.execute(
            f"INSERT INTO {table} ({fields}) VALUES ({placeholders})",
            tuple(values.values()),
        )


# ---------------------------------------------------------
# MIGRATIONS
# ---------------------------------------------------------

def run_migrations():
    print("🔧 Running DB migrations…")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # -------------------------------------------------
    # 0. Nettoyage legacy : suppression table logs (désormais obsolète)
    # -------------------------------------------------
    if table_exists(cursor, "logs"):
        print("🧹 Dropping legacy table: logs")
        cursor.execute("DROP TABLE IF EXISTS logs")
        conn.commit()

    # -------------------------------------------------
    # 0.1 Welcome email templates table (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "welcome_email_templates"):
        print("🛠 Creating table: welcome_email_templates")
        cursor.execute("""
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
        """)
        conn.commit()

    # -------------------------------------------------
    # 0.2 Stream policies tables (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "stream_policies"):
        print("🛠 Creating table: stream_policies")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stream_policies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          scope_type TEXT NOT NULL CHECK (scope_type IN ('global','server','user')),
          scope_id INTEGER,
          provider TEXT NULL CHECK (provider IN ('plex','jellyfin')),
          server_id INTEGER NULL,
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
          rule_value_json TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_policies_scope ON stream_policies(scope_type, scope_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_policies_enabled ON stream_policies(is_enabled, priority);")
        conn.commit()

    if not table_exists(cursor, "stream_enforcement_state"):
        print("🛠 Creating table: stream_enforcement_state")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stream_enforcement_state (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          policy_id INTEGER NOT NULL,
          server_id INTEGER NOT NULL,
          actor_key TEXT NOT NULL,
          vodum_user_id INTEGER,
          external_user_id TEXT,
          first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          warned_at TIMESTAMP,
          killed_at TIMESTAMP,
          last_reason TEXT,
          UNIQUE(policy_id, server_id, actor_key),
          FOREIGN KEY(policy_id) REFERENCES stream_policies(id) ON DELETE CASCADE,
          FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        );
        """)
        conn.commit()

    if not table_exists(cursor, "stream_enforcements"):
        print("🛠 Creating table: stream_enforcements")
        cursor.execute("""
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
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_enforcements_time ON stream_enforcements(created_at);")
        conn.commit()

    # ✅ IMPORTANT : migrations même si la table existe déjà
    ensure_column(cursor, "stream_enforcements", "account_username", "TEXT")
    ensure_column(cursor, "stream_enforcements", "ips_json", "TEXT")
    ensure_column(cursor, "stream_enforcements", "details_json", "TEXT")

    # -------------------------------------------------
    # 0.3 Tautulli import jobs
    # -------------------------------------------------
    if not table_exists(cursor, "tautulli_import_jobs"):
        print("🛠 Creating table: tautulli_import_jobs")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tautulli_import_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          server_id INTEGER NOT NULL, -- legacy (0 maintenant)
          file_path TEXT NOT NULL,

          
          keep_all_libraries INTEGER NOT NULL DEFAULT 0,
          import_only_available_libraries INTEGER NOT NULL DEFAULT 1,
          target_server_id INTEGER NOT NULL DEFAULT 0,
          keep_all_users   INTEGER NOT NULL DEFAULT 0,

          status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','success','error')),
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          stats_json TEXT,
          last_error TEXT
        );
        """)
        conn.commit()

    # ✅ IMPORTANT : ces migrations doivent être exécutées même si la table existe déjà
   
    
    ensure_column(cursor, "tautulli_import_jobs", "keep_all_libraries", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(cursor, "tautulli_import_jobs", "import_only_available_libraries", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(cursor, "tautulli_import_jobs", "target_server_id", "INTEGER NOT NULL DEFAULT 0")

    ensure_column(cursor, "tautulli_import_jobs", "keep_all_users", "INTEGER NOT NULL DEFAULT 0")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tautulli_import_jobs_status ON tautulli_import_jobs(status, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tautulli_import_jobs_server ON tautulli_import_jobs(server_id);")
    conn.commit()

    # -------------------------------------------------
    # 0.4 Monitoring snapshots table (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "monitoring_snapshots"):
        print("🛠 Creating table: monitoring_snapshots")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          live_sessions INTEGER NOT NULL DEFAULT 0,
          transcodes INTEGER NOT NULL DEFAULT 0
        );
        """)
        conn.commit()

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_snapshots_ts ON monitoring_snapshots(ts);")
    conn.commit()

    # -------------------------------------------------
    # 0.5 Monitoring server resources table (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "monitoring_server_resources"):
        print("🛠 Creating table: monitoring_server_resources")
        cursor.execute("""
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
        """)
        conn.commit()

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_monitoring_server_resources_fetched_at
        ON monitoring_server_resources(fetched_at);
    """)
    conn.commit()

    # -------------------------------------------------
    # Tasks scheduler mode migrations
    # -------------------------------------------------

    ensure_column(cursor, "tasks", "schedule_mode", "TEXT DEFAULT 'cron'")
    ensure_column(cursor, "tasks", "interval_seconds", "INTEGER DEFAULT NULL")

    cursor.execute("""
        UPDATE tasks
        SET schedule_mode = 'cron'
        WHERE schedule_mode IS NULL
    """)

    conn.commit()

    # -------------------------------------------------
    # Convert worker tasks to interval mode
    # -------------------------------------------------

    cursor.execute("""
        UPDATE tasks
        SET
            schedule_mode = 'interval',
            interval_seconds = CASE
                WHEN name = 'stream_enforcer' THEN 15
                ELSE 60
            END
        WHERE name IN (
            'monitor_enqueue_refresh',
            'media_jobs_worker',
            'stream_enforcer'
        )
        AND (
            schedule_mode IS NULL
            OR schedule_mode = 'cron'
            OR name = 'stream_enforcer'
        )
    """)

    cursor.execute("""
        UPDATE tasks
        SET
            schedule_mode = 'interval',
            interval_seconds = 120
        WHERE name = 'apply_plex_access_updates'
        AND (
            schedule_mode IS NULL
            OR schedule_mode = 'cron'
        )
    """)

    conn.commit()

    # -------------------------------------------------
    # 1. Vérifier que toutes les tables existent
    # -------------------------------------------------

    REQUIRED_TABLES = {
        "vodum_users": [],
        "media_users": [],
        "servers": [],
        "libraries": [],
        "media_user_libraries": [],
        "email_templates": [],
        "sent_emails": [],
        "settings": [],
        "user_identities": [],
        "media_jobs": [],
        "tautulli_import_jobs": [],
        "tasks": []
    }


    for table in REQUIRED_TABLES:
        if not table_exists(cursor, table):
            raise RuntimeError(f"❌ ERROR: table '{table}' does not exist ! "
                               f"-> Check that tables.sql has been imported correctly.")

    ensure_column(cursor, "servers", "server_version", "TEXT DEFAULT NULL")

    # Temporary cooldown for unreachable media servers.
    # Used to avoid hammering a down server from monitoring/sync tasks.
    ensure_column(cursor, "servers", "unavailable_since", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "servers", "cooldown_until", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "servers", "last_failure", "TEXT DEFAULT NULL")
    # Jellyfin stored password (1 password per media account/server)
    ensure_column(cursor, "media_users", "stored_password", "TEXT DEFAULT NULL")
    conn.commit()


    # -------------------------------------------------
    # TELEMETRY SETTINGS
    # -------------------------------------------------
    ensure_column(cursor, "settings", "enable_anonymous_telemetry", "INTEGER DEFAULT 1")
    ensure_column(cursor, "settings", "telemetry_instance_id", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "telemetry_last_sent_at", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "task_defaults_version", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "stream_enforcer_boost_until", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "settings", "subscription_plans_enabled_only", "INTEGER DEFAULT 0")
    conn.commit()

    # -------------------------------------------------
    # USER REFERRAL SETTINGS
    # -------------------------------------------------
    if not table_exists(cursor, "user_referral_settings"):
        print("🛠 Creating table: user_referral_settings")
        cursor.execute("""
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

    ensure_row(cursor, "user_referral_settings", "id = :id", {
        "id": 1,
        "enabled": 0,
        "reward_enabled": 1,
        "qualification_days": 60,
        "reward_days": 60,
        "allow_referrer_change_before_qualification": 1,
        "auto_notify_reward": 1,
        "eligible_statuses": "active",
    })
    conn.commit()

    # -------------------------------------------------
    # USER REFERRALS
    # -------------------------------------------------
    if not table_exists(cursor, "user_referrals"):
        print("🛠 Creating table: user_referrals")
        cursor.execute("""
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
            FOREIGN KEY(referred_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referrals_referrer_user_id ON user_referrals(referrer_user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referrals_status ON user_referrals(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referrals_qualification_due_at ON user_referrals(qualification_due_at);")
        conn.commit()

    ensure_column(cursor, "user_referrals", "notification_template_id", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "user_referrals", "last_error", "TEXT DEFAULT NULL")
    ensure_column(cursor, "user_referrals", "expired_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "user_referrals", "archived_at", "TIMESTAMP DEFAULT NULL")

    # -------------------------------------------------
    # MIGRATION: refresh old referral status CHECK constraint
    # SQLite cannot ALTER CHECK constraints directly
    # -------------------------------------------------

    try:
        cursor.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type='table'
              AND name='user_referrals'
        """)

        row = cursor.fetchone()
        table_sql = (row[0] or "") if row else ""

        if (
            "'expired'" not in table_sql
            or "'archived'" not in table_sql
        ):

            print("🛠 Migrating user_referrals CHECK constraint...")

            cursor.execute("""
                ALTER TABLE user_referrals
                RENAME TO user_referrals_old
            """)

            cursor.execute("""
            CREATE TABLE user_referrals (
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
                FOREIGN KEY(referred_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
            );
            """)

            cursor.execute("""
                INSERT INTO user_referrals (
                    id,
                    referrer_user_id,
                    referred_user_id,
                    status,
                    referral_source,
                    start_at,
                    qualification_due_at,
                    qualified_at,
                    qualification_days_snapshot,
                    reward_days_snapshot,
                    reward_granted_at,
                    reward_expiration_before,
                    reward_expiration_after,
                    expired_at,
                    archived_at,
                    notification_sent_at,
                    notification_template_id,
                    last_error,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    referrer_user_id,
                    referred_user_id,
                    status,
                    referral_source,
                    start_at,
                    qualification_due_at,
                    qualified_at,
                    qualification_days_snapshot,
                    reward_days_snapshot,
                    reward_granted_at,
                    reward_expiration_before,
                    reward_expiration_after,
                    expired_at,
                    archived_at,
                    notification_sent_at,
                    notification_template_id,
                    last_error,
                    created_at,
                    updated_at
                FROM user_referrals_old
            """)

            cursor.execute("DROP TABLE user_referrals_old")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_referrals_referrer_user_id
                ON user_referrals(referrer_user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_referrals_status
                ON user_referrals(status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_referrals_qualification_due_at
                ON user_referrals(qualification_due_at)
            """)

            conn.commit()

            print("✅ user_referrals CHECK constraint migrated")

    except Exception as e:
        print(f"❌ Failed migrating user_referrals constraint: {e}")

    ensure_column(cursor, "user_referral_settings", "auto_expire_pending", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(cursor, "user_referral_settings", "auto_archive_rewarded", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(cursor, "user_referral_settings", "auto_archive_expired", "INTEGER NOT NULL DEFAULT 1")

    ensure_column(cursor, "user_referral_settings", "rewarded_archive_days", "INTEGER NOT NULL DEFAULT 90")
    ensure_column(cursor, "user_referral_settings", "expired_archive_days", "INTEGER NOT NULL DEFAULT 30")

    conn.commit()

    # -------------------------------------------------
    # USER REFERRAL EVENTS
    # -------------------------------------------------
    if not table_exists(cursor, "user_referral_events"):
        print("🛠 Creating table: user_referral_events")
        cursor.execute("""
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
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_referral_events_referral_id ON user_referral_events(referral_id);")
        conn.commit()

    print("✔ All tables exist.")

    # -------------------------------------------------
    # 1.1 Upgrade vodum_users.status CHECK constraint (NEW statuses)
    # -------------------------------------------------
    def vodum_users_has_new_statuses():
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='vodum_users'")
        row = cursor.fetchone()
        if not row or not row[0]:
            return False
        sql = row[0].lower()
        return ("'invited'" in sql) and ("'unknown'" in sql)

    if table_exists(cursor, "vodum_users") and not vodum_users_has_new_statuses():
        print("🛠 Upgrading vodum_users.status CHECK (add invited/unfriended/suspended/unknown)")
        cursor.execute("ALTER TABLE vodum_users RENAME TO vodum_users_old")

        cursor.execute("""
        CREATE TABLE vodum_users (
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

            status TEXT DEFAULT 'expired'
              CHECK (status IN (
                'active','pre_expired','reminder','expired',
                'invited','unfriended','suspended','unknown'
              )),
            last_status TEXT,
            status_changed_at TIMESTAMP
        );
        """)

        cursor.execute("""
        INSERT INTO vodum_users (
            id, username, firstname, lastname, email, second_email,
            expiration_date, renewal_method, renewal_date, created_at,
            notes, status, last_status, status_changed_at
        )
        SELECT
            id, username, firstname, lastname, email, second_email,
            expiration_date, renewal_method, renewal_date, created_at,
            notes, status, last_status, status_changed_at
        FROM vodum_users_old;
        """)

        cursor.execute("DROP TABLE vodum_users_old")
        conn.commit()
        print("✔ vodum_users.status constraint upgraded.")

    # 1.2 vodum_users per-user stream override 
    ensure_column(cursor, "vodum_users", "max_streams_override", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "notifications_order_override", "TEXT DEFAULT NULL")

    # vodum_users per-user expiration date override
    ensure_column(cursor, "vodum_users", "expiration_date_override", "INTEGER DEFAULT 0")

    # Missing columns on upgraded databases
    ensure_column(cursor, "vodum_users", "renewal_method", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "renewal_date", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "referrer_user_id", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "last_status", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "status_changed_at", "TIMESTAMP DEFAULT NULL")

    # Subscription template assignment
    ensure_column(cursor, "vodum_users", "subscription_template_id", "INTEGER DEFAULT NULL")


    # -------------------------------------------------
    # 1.3 Subscription templates (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "subscription_templates"):
        print("🛠 Creating table: subscription_templates")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_templates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          notes TEXT,
          duration_days INTEGER DEFAULT 30,
          subscription_value REAL DEFAULT 0,
          policies_json TEXT NOT NULL DEFAULT '[]',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

    ensure_column(cursor, "subscription_templates", "duration_days", "INTEGER DEFAULT 30")
    ensure_column(cursor, "subscription_templates", "subscription_value", "REAL DEFAULT 0")
    ensure_column(cursor, "subscription_templates", "is_default", "INTEGER DEFAULT 0")
    ensure_column(cursor, "subscription_templates", "is_enabled", "INTEGER DEFAULT 1")
    ensure_column(cursor, "subscription_templates", "is_lifetime", "INTEGER DEFAULT 0")
    conn.commit()

    # Seed marker: default subscription templates must be inserted only once.
    # If the admin deletes them later, they must not come back automatically at next boot.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_template_seed_state (
            seed_key TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    bundled_templates = [
        (
            "base sub",
            "2 streams / Same IP",
            365,
            10,
            0,
            0,
            '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}},{"rule_type":"max_streams_per_ip","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
        ),
        (
            "Family sub",
            "4 streams",
            365,
            30,
            0,
            0,
            '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":4,"allow_local_ip":true}}]',
        ),
        (
            "Plus sub",
            "3 streams / 2 IP",
            365,
            20,
            0,
            0,
            '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":3,"allow_local_ip":true}},{"rule_type":"max_ips_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
        ),
    ]

    cursor.execute(
        "SELECT seed_key FROM subscription_template_seed_state WHERE seed_key = ?",
        ("default_subscription_templates",),
    )
    default_templates_already_seeded = cursor.fetchone() is not None

    if not default_templates_already_seeded:
        cursor.execute("SELECT COUNT(*) FROM subscription_templates")
        templates_count = int(cursor.fetchone()[0] or 0)

        if templates_count == 0:
            print("🛠 Creating bundled default subscription templates")
            for name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json in bundled_templates:
                cursor.execute(
                    """
                    INSERT INTO subscription_templates(
                        name,
                        notes,
                        duration_days,
                        subscription_value,
                        is_default,
                        is_enabled,
                        policies_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        notes,
                        duration_days,
                        subscription_value,
                        is_default,
                        is_enabled,
                        policies_json,
                    ),
                )

        cursor.execute(
            "INSERT OR IGNORE INTO subscription_template_seed_state(seed_key) VALUES (?)",
            ("default_subscription_templates",),
        )
        conn.commit()




    # -------------------------------------------------
    # 2. Vérifier que toutes les colonnes obligatoires existent
    # -------------------------------------------------

    TASK_COLUMNS = {
        "name": "TEXT UNIQUE NOT NULL",
        "description": "TEXT",
        "schedule": "TEXT",
        "enabled": "INTEGER DEFAULT 1",
        "enabled_prev": "INTEGER DEFAULT NULL",
        "status": "TEXT",
        "last_run": "TIMESTAMP",
        "next_run": "TIMESTAMP",
        "last_error": "TEXT",
        "queued_count": "INTEGER NOT NULL DEFAULT 0",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "max_retries": "INTEGER NOT NULL DEFAULT 3",
        "last_attempt_at": "TIMESTAMP",
        "next_retry_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }

    for col, definition in TASK_COLUMNS.items():
        ensure_column(cursor, "tasks", col, definition)

    print("✔ Task columns verified.")

    # -------------------------------------------------
    # 2.1 Vérifier colonnes SETTINGS (migrations légères)
    # -------------------------------------------------
    ensure_column(cursor, "settings", "brand_name", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "email_history_retention_years", "INTEGER DEFAULT 2")
    ensure_column(cursor, "settings", "backup_retention_days", "INTEGER DEFAULT 30")
    ensure_column(cursor, "settings", "data_retention_years", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "skip_never_used_accounts", "INTEGER DEFAULT 0")

    # Plex settings
    ensure_column(cursor, "settings", "plex_user_import_mode", "TEXT DEFAULT 'global'")


    
    # Auth admin
    ensure_column(cursor, "settings", "admin_password_hash", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "auth_enabled", "INTEGER DEFAULT 1")
    ensure_column(cursor, "settings", "web_secure_cookies", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "web_cookie_samesite", "TEXT DEFAULT 'Lax'")
    ensure_column(cursor, "settings", "web_trust_proxy", "INTEGER DEFAULT 0")
    print("✔ Settings columns verified (brand_name).")
    # -------------------------------------------------
    # Anti brute-force login
    # -------------------------------------------------
    if not table_exists(cursor, "auth_login_attempts"):
        print("🛠 Creating table: auth_login_attempts")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL CHECK(scope IN ('ip', 'email')),
            scope_value TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            first_failed_at TIMESTAMP DEFAULT NULL,
            last_failed_at TIMESTAMP DEFAULT NULL,
            locked_until TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scope, scope_value)
        );
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_scope "
            "ON auth_login_attempts(scope, scope_value);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_locked_until "
            "ON auth_login_attempts(locked_until);"
        )
        conn.commit()
    
    # -------------------------------------------------
    # 2.1.1 Discord settings + user fields (NEW)
    # -------------------------------------------------
    ensure_column(cursor, "settings", "discord_enabled", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "discord_bot_token", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "discord_bot_id", "INTEGER DEFAULT NULL")

    # Table to store one or multiple Discord bot configurations
    if not table_exists(cursor, "discord_bots"):
        print("🛠 Creating table: discord_bots")
        cursor.execute("""
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
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_discord_bots_type ON discord_bots(bot_type);")
        conn.commit()

    # One-time migration: move legacy settings.discord_bot_token into discord_bots
    try:
        cursor.execute("SELECT discord_bot_id, discord_bot_token FROM settings WHERE id = 1")
        srow = cursor.fetchone()
        legacy_bot_id = srow[0] if srow else None
        legacy_token = (srow[1] or '').strip() if srow else ''

        if (legacy_bot_id is None or legacy_bot_id == 0) and legacy_token:
            # create a bot record
            cursor.execute("""
                INSERT INTO discord_bots(name, token, bot_type)
                VALUES(?, ?, 'custom')
            """, ("Primary bot", legacy_token))
            new_id = cursor.lastrowid
            cursor.execute("UPDATE settings SET discord_bot_id = ? WHERE id = 1", (new_id,))
            conn.commit()
            print("➕ Migrated legacy discord_bot_token into discord_bots (Primary bot)")
    except Exception as e:
        # non-fatal
        print(f"⚠️ Discord bots migration skipped: {e}")
    ensure_column(cursor, "settings", "notifications_order", "TEXT DEFAULT 'email'")
    ensure_column(cursor, "settings", "user_notifications_can_override", "INTEGER DEFAULT 0")
    ensure_column(cursor, "settings", "notifications_send_mode", "TEXT DEFAULT 'first'")
    cursor.execute("UPDATE settings SET notifications_order = COALESCE(NULLIF(TRIM(notifications_order),''), 'email') WHERE id = 1")
    # Expiration handling mode (NEW)
    # - 'disable' : disable access immediately on expiration (task disable_expired_users)
    # - 'warn_then_disable' : create a system policy at expiration, then disable access after X days
    ensure_column(cursor, "settings", "expiry_mode", "TEXT DEFAULT 'disable'")
    ensure_column(cursor, "settings", "warn_then_disable_days", "INTEGER DEFAULT 7")

    ensure_column(cursor, "vodum_users", "discord_user_id", "TEXT DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "discord_name", "TEXT DEFAULT NULL")

    # Tables Discord (templates + history + campaigns)
    if not table_exists(cursor, "discord_templates"):
        print("🛠 Creating table: discord_templates")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS discord_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT UNIQUE NOT NULL CHECK(type IN ('preavis','relance','fin')),
            title TEXT,
            body TEXT
        );
        """)
        conn.commit()

    if not table_exists(cursor, "sent_discord"):
        print("🛠 Creating table: sent_discord")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_discord (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            template_type TEXT NOT NULL,
            expiration_date TEXT,
            sent_at INTEGER,
            UNIQUE(user_id, template_type, expiration_date),
            FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE CASCADE
        );
        """)
        conn.commit()

    if not table_exists(cursor, "discord_campaigns"):
        print("🛠 Creating table: discord_campaigns")
        cursor.execute("""
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
        """)
        conn.commit()

    # Seed default discord templates (only if missing)
    defaults = {
        "preavis": (
            "⏳ Subscription expiring soon",
            "Hi {username}! You have {days_left} day(s) left. Your subscription expires on {expiration_date}."
        ),
        "relance": (
            "🔔 Subscription reminder",
            "Hello {username} 🙂 Just a reminder: your subscription expires on {expiration_date} ({days_left} day(s) left)."
        ),
        "fin": (
            "⚠️ Subscription expired",
            "Hi {username}. Your subscription expired on {expiration_date}. Please contact me to renew it."
        ),
    }

    for k, (title, body) in defaults.items():
        cursor.execute("SELECT 1 FROM discord_templates WHERE type=?", (k,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO discord_templates(type, title, body) VALUES(?,?,?)",
                (k, title, body),
            )
            print(f"➕ Default discord template inserted: {k}")
    conn.commit()



    # -------------------------------------------------
    # 2.1.2 Communications (Unified) tables + migration (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "comm_templates"):
        print("🛠 Creating table: comm_templates")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
            days_before INTEGER DEFAULT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trigger_event TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked')),
            trigger_provider TEXT NOT NULL DEFAULT 'all' CHECK(trigger_provider IN ('all','plex','jellyfin')),
            expiration_change_direction TEXT NOT NULL DEFAULT 'all' CHECK(expiration_change_direction IN ('all','increase','decrease')),
            days_after INTEGER DEFAULT NULL,
            subscription_scope TEXT NOT NULL DEFAULT 'none' CHECK(subscription_scope IN ('none','all','specific')),
            subscription_template_id INTEGER DEFAULT NULL,
            FOREIGN KEY(subscription_template_id) REFERENCES subscription_templates(id) ON DELETE SET NULL
        );
        """)
        conn.commit()

    ensure_column(
        cursor,
        "comm_templates",
        "trigger_event",
        "TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked'))",
    )
    ensure_column(
        cursor,
        "comm_templates",
        "trigger_provider",
        "TEXT NOT NULL DEFAULT 'all' CHECK(trigger_provider IN ('all','plex','jellyfin'))",
    )
    ensure_column(
        cursor,
        "comm_templates",
        "expiration_change_direction",
        "TEXT NOT NULL DEFAULT 'all' CHECK(expiration_change_direction IN ('all','increase','decrease'))",
    )
    ensure_column(cursor, "comm_templates", "days_after", "INTEGER DEFAULT NULL")
    ensure_column(
        cursor,
        "comm_templates",
        "subscription_scope",
        "TEXT NOT NULL DEFAULT 'none' CHECK(subscription_scope IN ('none','all','specific'))",
    )
    ensure_column(cursor, "comm_templates", "subscription_template_id", "INTEGER DEFAULT NULL")
    conn.commit()

    def comm_templates_schema_needs_upgrade():
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='comm_templates'")
        row = cursor.fetchone()
        if not row or not row[0]:
            return True
        sql = (row[0] or "").lower()
        if "'expiration_change'" not in sql:
            return True
        if "'pending_invite_reminder'" not in sql:
            return True
        if "'stream_blocked'" not in sql:
            return True
        if "expiration_change_direction" not in sql:
            return True
        return False

    if table_exists(cursor, "comm_templates") and comm_templates_schema_needs_upgrade():
        print("🛠 Upgrading comm_templates schema (add expiration_change trigger + direction)")
        cursor.execute("PRAGMA legacy_alter_table=ON")
        cursor.execute("ALTER TABLE comm_templates RENAME TO comm_templates_old")

        cursor.execute("""
        CREATE TABLE comm_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
            days_before INTEGER DEFAULT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trigger_event TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked')),
            trigger_provider TEXT NOT NULL DEFAULT 'all' CHECK(trigger_provider IN ('all','plex','jellyfin')),
            expiration_change_direction TEXT NOT NULL DEFAULT 'all' CHECK(expiration_change_direction IN ('all','increase','decrease')),
            days_after INTEGER DEFAULT NULL,
            subscription_scope TEXT NOT NULL DEFAULT 'none' CHECK(subscription_scope IN ('none','all','specific')),
            subscription_template_id INTEGER DEFAULT NULL,
            FOREIGN KEY(subscription_template_id) REFERENCES subscription_templates(id) ON DELETE SET NULL
        );
        """)

        cursor.execute("""
        INSERT INTO comm_templates (
            id, key, name, enabled, days_before, subject, body,
            created_at, updated_at, trigger_event, trigger_provider,
            expiration_change_direction, days_after,
            subscription_scope, subscription_template_id
        )
        SELECT
            id, key, name, enabled, days_before, subject, body,
            created_at, updated_at, trigger_event, trigger_provider,
            'all',
            days_after,
            COALESCE(subscription_scope, 'none'),
            subscription_template_id
        FROM comm_templates_old
        """)

        cursor.execute("DROP TABLE comm_templates_old")
        cursor.execute("PRAGMA legacy_alter_table=OFF")
        conn.commit()
        print("✔ comm_templates schema upgraded.")

    # -------------------------------------------------
    # System communication template: stream blocked
    # -------------------------------------------------
    cursor.execute(
        """
        SELECT id, subject, body
        FROM comm_templates
        WHERE key = 'stream_blocked'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    stream_blocked_subject = "Playback blocked"
    stream_blocked_body = (
        "Hello {firstusername},\n\n"
        "Your playback has been stopped by VODUM.\n\n"
        "Reason: {policy_reason}\n"
        "Media: {media_title}\n"
        "Server: {server_name}\n"
        "Device: {device_name}\n"
        "Client: {client_name}\n"
        "Time: {blocked_at}\n\n"
        "If you think this is a mistake, please contact the administrator.\n\n"
        "Best regards,\n"
        "{brand_name}\n"
    )

    if not row:
        print("➕ Default communication template inserted: stream_blocked")
        cursor.execute(
            """
            INSERT INTO comm_templates(
                key,
                name,
                enabled,
                trigger_event,
                trigger_provider,
                expiration_change_direction,
                subscription_scope,
                subscription_template_id,
                days_before,
                days_after,
                subject,
                body,
                created_at,
                updated_at
            )
            VALUES(
                'stream_blocked',
                'Stream blocked',
                0,
                'stream_blocked',
                'all',
                'all',
                'all',
                NULL,
                NULL,
                0,
                ?,
                ?,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """,
            (stream_blocked_subject, stream_blocked_body),
        )
    else:
        cursor.execute(
            """
            UPDATE comm_templates
            SET name = CASE
                    WHEN name IS NULL OR TRIM(name) = '' THEN 'Stream blocked'
                    ELSE name
                END,
                trigger_event = 'stream_blocked',
                trigger_provider = 'all',
                expiration_change_direction = 'all',
                subscription_scope = 'all',
                subscription_template_id = NULL,
                days_before = NULL,
                days_after = 0,
                subject = CASE
                    WHEN subject IS NULL OR TRIM(subject) = '' THEN ?
                    ELSE subject
                END,
                body = CASE
                    WHEN body IS NULL OR TRIM(body) = '' THEN ?
                    ELSE body
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = 'stream_blocked'
            """,
            (stream_blocked_subject, stream_blocked_body),
        )

    cursor.execute(
        """
        SELECT expiry_mode
        FROM settings
        WHERE id = 1
        """
    )
    settings_row = cursor.fetchone()
    expiry_mode = settings_row[0] if settings_row else "none"

    if expiry_mode in ("warn_only", "warn_then_disable"):
        cursor.execute(
            """
            UPDATE comm_templates
            SET enabled = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = 'stream_blocked'
            """
        )

    conn.commit()


    # -------------------------------------------------
    # Communications scheduled queue (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "comm_scheduled"):
        print("🛠 Creating table: comm_scheduled")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_scheduled (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            vodum_user_id INTEGER NOT NULL,
            provider TEXT NOT NULL CHECK(provider IN ('plex','jellyfin')),
            server_id INTEGER,
            send_at TIMESTAMP NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','error')),
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE,
            FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_due ON comm_scheduled(status, send_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_user ON comm_scheduled(vodum_user_id);")
        conn.commit()

    # -------------------------------------------------
    # comm_scheduled: retry / payload / dedupe support
    # -------------------------------------------------
    ensure_column(cursor, "comm_scheduled", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(cursor, "comm_scheduled", "max_attempts", "INTEGER NOT NULL DEFAULT 10")
    ensure_column(cursor, "comm_scheduled", "next_attempt_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "comm_scheduled", "last_attempt_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "comm_scheduled", "payload_json", "TEXT DEFAULT NULL")
    ensure_column(cursor, "comm_scheduled", "dedupe_key", "TEXT DEFAULT NULL")
    ensure_column(cursor, "comm_scheduled", "channels_sent", "TEXT DEFAULT NULL")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_retry ON comm_scheduled(status, next_attempt_at)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_scheduled_dedupe ON comm_scheduled(dedupe_key)")
    conn.commit()

    if not table_exists(cursor, "comm_template_attachments"):
        print("🛠 Creating table: comm_template_attachments")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_template_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            mime_type TEXT,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_template_attachments_template ON comm_template_attachments(template_id);")
        conn.commit()

    if not table_exists(cursor, "comm_campaigns"):
        print("🛠 Creating table: comm_campaigns")
        cursor.execute("""
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
        """)
        conn.commit()

    ensure_column(cursor, "comm_campaigns", "trigger_provider", "TEXT DEFAULT 'all'")
    ensure_column(cursor, "comm_campaigns", "subscription_scope", "TEXT DEFAULT 'none'")
    ensure_column(cursor, "comm_campaigns", "subscription_template_id", "INTEGER DEFAULT NULL")

    cursor.execute("""
        UPDATE comm_campaigns
        SET trigger_provider = 'all'
        WHERE trigger_provider IS NULL
           OR TRIM(trigger_provider) = ''
    """)

    cursor.execute("""
        UPDATE comm_campaigns
        SET subscription_scope = 'none'
        WHERE subscription_scope IS NULL
           OR TRIM(subscription_scope) = ''
    """)

    if not table_exists(cursor, "comm_campaign_attachments"):
        print("🛠 Creating table: comm_campaign_attachments")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_campaign_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            mime_type TEXT,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_campaign_attachments_campaign ON comm_campaign_attachments(campaign_id);")
        conn.commit()

    if not table_exists(cursor, "comm_campaign_targets"):
        print("🛠 Creating table: comm_campaign_targets")
        cursor.execute("""
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
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_campaign_targets_campaign ON comm_campaign_targets(campaign_id, status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_campaign_targets_retry ON comm_campaign_targets(status, next_attempt_at);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_campaign_targets_dedupe ON comm_campaign_targets(dedupe_key);")
        conn.commit()

    ensure_column(cursor, "comm_campaign_targets", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(cursor, "comm_campaign_targets", "max_attempts", "INTEGER NOT NULL DEFAULT 10")
    ensure_column(cursor, "comm_campaign_targets", "next_attempt_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "comm_campaign_targets", "last_attempt_at", "TIMESTAMP DEFAULT NULL")
    ensure_column(cursor, "comm_campaign_targets", "last_error", "TEXT")
    ensure_column(cursor, "comm_campaign_targets", "channels_sent", "TEXT DEFAULT NULL")
    ensure_column(cursor, "comm_campaign_targets", "dedupe_key", "TEXT DEFAULT NULL")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_campaign_targets_campaign ON comm_campaign_targets(campaign_id, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_campaign_targets_retry ON comm_campaign_targets(status, next_attempt_at);")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_campaign_targets_dedupe ON comm_campaign_targets(dedupe_key);")
    conn.commit()

    if not table_exists(cursor, "comm_history"):
        print("🛠 Creating table: comm_history")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL CHECK(kind IN ('template','campaign')),
          template_id INTEGER NULL,
          campaign_id INTEGER NULL,
          user_id INTEGER NULL,
          -- Real delivery history only:
          -- no technical/system rows, no "skipped" rows
          channel_used TEXT NOT NULL CHECK(channel_used IN ('email','discord')),
          status TEXT NOT NULL CHECK(status IN ('sent','failed')),
          error TEXT NULL,
          sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          meta_json TEXT NULL,
          FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE SET NULL,
          FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE SET NULL,
          FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_history_sent_at ON comm_history(sent_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_history_user ON comm_history(user_id, sent_at DESC);")
        conn.commit()

    # -------------------------------------------------
    # Repair old DBs where SQLite rewrote foreign keys
    # from comm_templates to comm_templates_old during
    # the comm_templates schema upgrade.
    # -------------------------------------------------
    def _table_references_comm_templates_old(table_name):
        if not table_exists(cursor, table_name):
            return False

        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        return any((row[2] or "") == "comm_templates_old" for row in cursor.fetchall() or [])

    def _repair_comm_scheduled_fk():
        if not _table_references_comm_templates_old("comm_scheduled"):
            return

        print("🛠 Repairing comm_scheduled foreign key: comm_templates_old -> comm_templates")

        cursor.execute("ALTER TABLE comm_scheduled RENAME TO comm_scheduled_old")

        cursor.execute("""
        CREATE TABLE comm_scheduled (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            vodum_user_id INTEGER NOT NULL,
            provider TEXT NOT NULL CHECK(provider IN ('plex','jellyfin')),
            server_id INTEGER,
            send_at TIMESTAMP NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','error')),
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 10,
            next_attempt_at TIMESTAMP DEFAULT NULL,
            last_attempt_at TIMESTAMP DEFAULT NULL,
            payload_json TEXT DEFAULT NULL,
            dedupe_key TEXT DEFAULT NULL,
            channels_sent TEXT DEFAULT NULL,
            FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE,
            FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id) ON DELETE CASCADE,
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
        );
        """)

        cursor.execute("""
        INSERT INTO comm_scheduled(
            id, template_id, vodum_user_id, provider, server_id, send_at,
            status, last_error, created_at, updated_at,
            attempt_count, max_attempts, next_attempt_at, last_attempt_at,
            payload_json, dedupe_key, channels_sent
        )
        SELECT
            id, template_id, vodum_user_id, provider, server_id, send_at,
            status, last_error, created_at, updated_at,
            COALESCE(attempt_count, 0),
            COALESCE(max_attempts, 10),
            next_attempt_at,
            last_attempt_at,
            payload_json,
            dedupe_key,
            channels_sent
        FROM comm_scheduled_old
        """)

        cursor.execute("DROP TABLE comm_scheduled_old")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_due ON comm_scheduled(status, send_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_user ON comm_scheduled(vodum_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_retry ON comm_scheduled(status, next_attempt_at)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_scheduled_dedupe ON comm_scheduled(dedupe_key)")

    def _repair_comm_template_attachments_fk():
        if not _table_references_comm_templates_old("comm_template_attachments"):
            return

        print("🛠 Repairing comm_template_attachments foreign key: comm_templates_old -> comm_templates")

        cursor.execute("ALTER TABLE comm_template_attachments RENAME TO comm_template_attachments_old")

        cursor.execute("""
        CREATE TABLE comm_template_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            mime_type TEXT,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        INSERT INTO comm_template_attachments(
            id, template_id, filename, mime_type, path, created_at
        )
        SELECT
            id, template_id, filename, mime_type, path, created_at
        FROM comm_template_attachments_old
        """)

        cursor.execute("DROP TABLE comm_template_attachments_old")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_template_attachments_template ON comm_template_attachments(template_id)")

    def _repair_comm_history_fk():
        if not _table_references_comm_templates_old("comm_history"):
            return

        print("🛠 Repairing comm_history foreign key: comm_templates_old -> comm_templates")

        cursor.execute("ALTER TABLE comm_history RENAME TO comm_history_old")

        cursor.execute("""
        CREATE TABLE comm_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL CHECK(kind IN ('template','campaign')),
          template_id INTEGER NULL,
          campaign_id INTEGER NULL,
          user_id INTEGER NULL,
          channel_used TEXT NOT NULL CHECK(channel_used IN ('email','discord')),
          status TEXT NOT NULL CHECK(status IN ('sent','failed')),
          error TEXT NULL,
          sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          meta_json TEXT NULL,
          FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE SET NULL,
          FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE SET NULL,
          FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
        );
        """)

        cursor.execute("""
        INSERT INTO comm_history(
            id, kind, template_id, campaign_id, user_id,
            channel_used, status, error, sent_at, meta_json
        )
        SELECT
            id, kind, template_id, campaign_id, user_id,
            channel_used, status, error, sent_at, meta_json
        FROM comm_history_old
        """)

        cursor.execute("DROP TABLE comm_history_old")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_history_sent_at ON comm_history(sent_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_history_user ON comm_history(user_id, sent_at DESC)")

    _repair_comm_scheduled_fk()
    _repair_comm_template_attachments_fk()
    _repair_comm_history_fk()
    conn.commit()

    # One-time migration (best effort, no data loss): old → unified
    try:
        cursor.execute("SELECT COUNT(*) FROM comm_templates")
        comm_tpl_count = int(cursor.fetchone()[0] or 0)

        # Migrate templates only once (when comm_templates is empty)
        if comm_tpl_count == 0 and (table_exists(cursor, "email_templates") or table_exists(cursor, "discord_templates")):
            import json as _json
            print("🔁 Migrating templates: email_templates + discord_templates → comm_templates")

            # Read current global delays (legacy) as a starting point for days_before
            preavis_days = None
            relance_days = None
            try:
                cursor.execute("SELECT preavis_days, reminder_days FROM settings WHERE id = 1")
                r = cursor.fetchone()
                if r:
                    preavis_days = int(r[0]) if r[0] is not None else None
                    relance_days = int(r[1]) if r[1] is not None else None
            except Exception:
                pass

            keys = ("preavis", "relance", "fin")
            for k in keys:
                e_subject = None
                e_body = None
                e_days = None
                if table_exists(cursor, "email_templates"):
                    try:
                        cursor.execute("SELECT subject, body, days_before FROM email_templates WHERE type = ?", (k,))
                        row = cursor.fetchone()
                        if row:
                            e_subject = row[0]
                            e_body = row[1]
                            e_days = row[2]
                    except Exception:
                        pass

                d_title = None
                d_body = None
                if table_exists(cursor, "discord_templates"):
                    try:
                        cursor.execute("SELECT title, body FROM discord_templates WHERE type = ?", (k,))
                        row = cursor.fetchone()
                        if row:
                            d_title = row[0]
                            d_body = row[1]
                    except Exception:
                        pass

                # Priority: email content, fallback to discord content
                subject = (e_subject or d_title or k).strip() if (e_subject or d_title) else k
                body = (e_body or d_body or "").strip()

                # days_before: prefer template-defined; fallback to legacy global settings for preavis/relance
                days_before = None
                if e_days is not None:
                    try:
                        days_before = int(e_days)
                    except Exception:
                        days_before = None
                if days_before is None:
                    if k == "preavis":
                        days_before = preavis_days
                    elif k == "relance":
                        days_before = relance_days

                name = k.capitalize()
                cursor.execute(
                    "INSERT INTO comm_templates(key, name, enabled, days_before, subject, body) VALUES(?, ?, 1, ?, ?, ?)",
                    (k, name, days_before, subject, body),
                )

            conn.commit()
            print("✅ Templates migrated into comm_templates")

        # Campaigns (mail + discord) → comm_campaigns (one-time when comm_campaigns is empty)
        cursor.execute("SELECT COUNT(*) FROM comm_campaigns")
        comm_c_count = int(cursor.fetchone()[0] or 0)
        if comm_c_count == 0 and (table_exists(cursor, "mail_campaigns") or table_exists(cursor, "discord_campaigns")):
            print("🔁 Migrating campaigns: mail_campaigns + discord_campaigns → comm_campaigns")

            if table_exists(cursor, "mail_campaigns"):
                cursor.execute("SELECT id, subject, body, server_id, status, is_test, created_at, finished_at FROM mail_campaigns ORDER BY id")
                for row in cursor.fetchall() or []:
                    mid, subject, body, server_id, status, is_test, created_at, finished_at = row
                    name = (subject or f"Mail campaign #{mid}")[:120]
                    sent_at = finished_at
                    cursor.execute(
                        "INSERT INTO comm_campaigns(name, subject, body, server_id, status, is_test, created_at, updated_at, sent_at) VALUES(?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP),COALESCE(?,CURRENT_TIMESTAMP),?)",
                        (name, subject or "", body or "", server_id, status or "pending", int(is_test or 0), created_at, created_at, sent_at),
                    )

            if table_exists(cursor, "discord_campaigns"):
                cursor.execute("SELECT id, title, body, server_id, is_test, status, created_at, sent_at, error FROM discord_campaigns ORDER BY id")
                for row in cursor.fetchall() or []:
                    did, title, body, server_id, is_test, status, created_at, sent_at, error = row
                    subject = title or f"Discord campaign #{did}"
                    name = subject[:120]
                    st = status
                    if st == "sent":
                        st = "finished"
                    elif st == "failed":
                        st = "error"
                    cursor.execute(
                        "INSERT INTO comm_campaigns(name, subject, body, server_id, status, is_test, created_at, updated_at, sent_at) VALUES(?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP),COALESCE(?,CURRENT_TIMESTAMP),?)",
                        (name, subject, body or "", server_id, st or "pending", int(is_test or 0), created_at, created_at, sent_at),
                    )

            conn.commit()
            print("✅ Campaigns migrated into comm_campaigns")

        # History (sent_emails + sent_discord) → comm_history (one-time when comm_history is empty)
        cursor.execute("SELECT COUNT(*) FROM comm_history")
        comm_h_count = int(cursor.fetchone()[0] or 0)
        if comm_h_count == 0:
            import json as _json
            tpl_map = {}
            try:
                cursor.execute("SELECT id, key FROM comm_templates")
                for r in cursor.fetchall() or []:
                    tpl_map[r[1]] = r[0]
            except Exception:
                tpl_map = {}

            if table_exists(cursor, "sent_emails"):
                print("🔁 Migrating history: sent_emails → comm_history")
                cursor.execute("SELECT user_id, template_type, expiration_date, sent_at FROM sent_emails ORDER BY id")
                for user_id, template_type, expiration_date, sent_at in cursor.fetchall() or []:
                    tid = tpl_map.get(template_type)
                    meta = {"template_key": template_type, "expiration_date": expiration_date}
                    # sent_at may be epoch integer (legacy)
                    inserted = False
                    if sent_at is not None:
                        try:
                            sent_at_i = int(str(sent_at).strip())
                            cursor.execute(
                                "INSERT INTO comm_history(kind, template_id, user_id, channel_used, status, error, sent_at, meta_json) "
                                "VALUES('template', ?, ?, 'email', 'sent', NULL, datetime(?, 'unixepoch'), ?)",
                                (tid, user_id, sent_at_i, _json.dumps(meta, ensure_ascii=False)),
                            )
                            inserted = True
                        except Exception:
                            inserted = False

                    if not inserted:
                        cursor.execute(
                            "INSERT INTO comm_history(kind, template_id, user_id, channel_used, status, error, sent_at, meta_json) "
                            "VALUES('template', ?, ?, 'email', 'sent', NULL, COALESCE(?, CURRENT_TIMESTAMP), ?)",
                            (tid, user_id, sent_at, _json.dumps(meta, ensure_ascii=False)),
                        )

            if table_exists(cursor, "sent_discord"):
                print("🔁 Migrating history: sent_discord → comm_history")
                cursor.execute("SELECT user_id, template_type, expiration_date, sent_at FROM sent_discord ORDER BY id")
                for user_id, template_type, expiration_date, sent_at in cursor.fetchall() or []:
                    tid = tpl_map.get(template_type)
                    meta = {"template_key": template_type, "expiration_date": expiration_date}

                    # sent_at may be epoch integer
                    inserted = False
                    if sent_at is not None:
                        try:
                            sent_at_i = int(sent_at)
                            cursor.execute(
                                "INSERT INTO comm_history(kind, template_id, user_id, channel_used, status, error, sent_at, meta_json) VALUES('template', ?, ?, 'discord', 'sent', NULL, datetime(?, 'unixepoch'), ?)",
                                (tid, user_id, sent_at_i, _json.dumps(meta, ensure_ascii=False)),
                            )
                            inserted = True
                        except Exception:
                            inserted = False

                    if not inserted:
                        cursor.execute(
                            "INSERT INTO comm_history(kind, template_id, user_id, channel_used, status, error, sent_at, meta_json) VALUES('template', ?, ?, 'discord', 'sent', NULL, CURRENT_TIMESTAMP, ?)",
                            (tid, user_id, _json.dumps(meta, ensure_ascii=False)),
                        )

            conn.commit()
            print("✅ History migrated into comm_history")
            # Best effort normalization: convert digit-only sent_at to datetime
            try:
                cursor.execute("""
                    UPDATE comm_history
                    SET sent_at = datetime(CAST(sent_at AS INTEGER), 'unixepoch')
                    WHERE (typeof(sent_at) = 'integer'
                           OR (typeof(sent_at) = 'text' AND TRIM(sent_at) GLOB '[0-9]*'))
                      AND length(TRIM(CAST(sent_at AS TEXT))) >= 10
                """)
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ Communications migration skipped: {e}")



    # -------------------------------------------------
    # 2.2 Ensure subscription_gifts table exists
    # -------------------------------------------------
    if not table_exists(cursor, "subscription_gift_runs"):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_gift_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

          target_type TEXT NOT NULL,
          target_server_id INTEGER NULL,

          days_added INTEGER NOT NULL,
          reason TEXT NULL,

          users_updated INTEGER NOT NULL DEFAULT 0
        )
        """)
        conn.commit()

    if not table_exists(cursor, "subscription_gift_run_users"):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_gift_run_users (
          run_id INTEGER NOT NULL,
          vodum_user_id INTEGER NOT NULL,
          PRIMARY KEY (run_id, vodum_user_id)
        )
        """)
        conn.commit()

    # -------------------------------------------------
    # 2.3 Monitoring tables (sessions + events)
    # -------------------------------------------------

    if not table_exists(cursor, "media_sessions"):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,

          server_id INTEGER NOT NULL,
          provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

          session_key TEXT NOT NULL,

          media_user_id INTEGER,
          external_user_id TEXT,

          media_key TEXT,
          media_type TEXT,
          title TEXT,
          grandparent_title TEXT,
          parent_title TEXT,

          state TEXT,
          progress_ms INTEGER,
          duration_ms INTEGER,

          is_transcode INTEGER DEFAULT 0 CHECK (is_transcode IN (0,1)),
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

          UNIQUE(server_id, session_key),

          FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
          FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
        )
        """)
        conn.commit()

    if not table_exists(cursor, "media_events"):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,

          server_id INTEGER NOT NULL,
          provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

          event_type TEXT NOT NULL,
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
        )
        """)
        conn.commit()

    # -------------------------------------------------
    # Monitoring: garantir l'unicité requise pour
    # ON CONFLICT(server_id, session_key)
    # -------------------------------------------------

    if table_exists(cursor, "media_sessions"):
        # Nettoyage d'éventuels doublons historiques avant création de l'index unique
        cursor.execute("""
        DELETE FROM media_sessions
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM media_sessions
            GROUP BY server_id, session_key
        )
        """)
        conn.commit()

        # IMPORTANT:
        # app/core/monitoring/collector.py utilise :
        #   ON CONFLICT(server_id, session_key) DO UPDATE
        # donc il faut absolument une contrainte UNIQUE correspondante
        cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_media_sessions_server_session
        ON media_sessions(server_id, session_key)
        """)
        conn.commit()

    # Index (idempotent)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_sessions_last_seen ON media_sessions(server_id, last_seen_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_sessions_user ON media_sessions(media_user_id, last_seen_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_events_ts ON media_events(server_id, ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_events_user_ts ON media_events(media_user_id, ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_events_type_ts ON media_events(event_type, ts)")
    conn.commit()

    print("✔ Monitoring tables verified (media_sessions, media_events).")

    # -------------------------------------------------
    # 2.4 Monitoring history table (aggregations)
    # -------------------------------------------------
    if not table_exists(cursor, "media_session_history"):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_session_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,

          server_id INTEGER NOT NULL,
          provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),

          -- Identifiants natifs
          session_key TEXT,
          media_key TEXT,
          external_user_id TEXT,

          -- Références internes (si résolues)
          media_user_id INTEGER,

          -- Infos média (snapshot)
          media_type TEXT,               -- movie/episode/track/unknown
          title TEXT,
          grandparent_title TEXT,
          parent_title TEXT,

          -- Timing
          started_at TIMESTAMP NOT NULL,
          stopped_at TIMESTAMP NOT NULL,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          watch_ms INTEGER NOT NULL DEFAULT 0,        -- progression estimée
          peak_bitrate INTEGER,
          was_transcode INTEGER NOT NULL DEFAULT 0,

          -- Client
          client_name TEXT,
          client_product TEXT,
          device TEXT,
          ip TEXT,

          -- Debug / futur
          raw_json TEXT,

          FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
          FOREIGN KEY(media_user_id) REFERENCES media_users(id) ON DELETE SET NULL
        )
        """)
    else:
        # Upgrade-safe : si la table existe déjà, on s'assure que les colonnes attendues existent.
        # (pratique si tu ajoutes des champs plus tard sans casser les DB existantes)
        ensure_column(cursor, "media_session_history", "peak_bitrate", "INTEGER")
        ensure_column(cursor, "media_session_history", "was_transcode", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(cursor, "media_session_history", "device", "TEXT")
        ensure_column(cursor, "media_session_history", "raw_json", "TEXT")
        ensure_column(cursor, "media_session_history", "ip", "TEXT")
        ensure_column(cursor, "media_session_history", "client_product", "TEXT")


    # Index pour stats rapides (safe avec IF NOT EXISTS)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_time ON media_session_history(started_at, stopped_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_user_time ON media_session_history(media_user_id, started_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msh_media_time ON media_session_history(media_key, started_at)")

    # Unique dedup index (required by collector upserts / imports)
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_tautulli_dedup
            ON media_session_history (server_id, media_user_id, started_at, media_key, client_name)
        """)
    except sqlite3.IntegrityError:
        # Existing DB may already contain duplicates -> dedupe once then retry
        print("🧹 Detected duplicates in media_session_history. Deduplicating before creating UNIQUE index…")

        # Keep the oldest row (MIN(id)) for each dedupe key
        cursor.execute("""
            DELETE FROM media_session_history
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM media_session_history
                GROUP BY server_id, media_user_id, started_at, media_key, client_name
            )
        """)

        # Retry index creation after cleanup
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_tautulli_dedup
            ON media_session_history (server_id, media_user_id, started_at, media_key, client_name)
        """)



    conn.commit()
    print("✔ Monitoring history table verified (media_session_history).")


    conn.commit()
    print("✔ Monitoring history table verified (media_session_history).")

    # -------------------------------------------------
    # 2.4+ Media jobs: queue robuste (status/lease/backoff/priority)
    # -------------------------------------------------
    if table_exists(cursor, "media_jobs"):
        # Colonnes modernes
        ensure_column(cursor, "media_jobs", "status",
                      "TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','success','error','canceled'))")
        ensure_column(cursor, "media_jobs", "priority", "INTEGER NOT NULL DEFAULT 100")
        ensure_column(cursor, "media_jobs", "run_after", "TIMESTAMP")
        ensure_column(cursor, "media_jobs", "locked_by", "TEXT")
        ensure_column(cursor, "media_jobs", "locked_until", "TIMESTAMP")
        ensure_column(cursor, "media_jobs", "max_attempts", "INTEGER NOT NULL DEFAULT 10")

        # Compat (certaines DB anciennes peuvent ne pas avoir ça)
        ensure_column(cursor, "media_jobs", "processed", "INTEGER NOT NULL DEFAULT 0 CHECK (processed IN (0,1))")
        ensure_column(cursor, "media_jobs", "success", "INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0,1))")
        ensure_column(cursor, "media_jobs", "attempts", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(cursor, "media_jobs", "dedupe_key", "TEXT")

        # ---- Indexes for monitoring / users (safe & idempotent) ----
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hist_user_stopped
            ON media_session_history (media_user_id, stopped_at)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hist_server_stopped
            ON media_session_history (server_id, stopped_at)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_history_server_library_stopped
            ON media_session_history (server_id, library_section_id, stopped_at)
            """
        )

        cursor.execute("DROP INDEX IF EXISTS uq_media_session_history_session")

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_media_session_history_session_lookup
            ON media_session_history (server_id, session_key, media_key, started_at)
            WHERE TRIM(COALESCE(session_key,'')) <> ''
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_media_users_vodum_user
            ON media_users (vodum_user_id)
            """
        )

        # Indexes queue
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_jobs_pick
        ON media_jobs(status, run_after, priority, created_at)
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_jobs_user ON media_jobs(vodum_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_jobs_server ON media_jobs(server_id)")
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_jobs_server_action
        ON media_jobs(server_id, provider, action, status)
        """)

        # Dédoublonnage (unique partiel)
        cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_media_jobs_dedupe_active
        ON media_jobs(dedupe_key)
        WHERE dedupe_key IS NOT NULL AND status IN ('queued','running');
        """)

        conn.commit()
        print("✔ Media jobs queue columns + indexes verified.")
    else:
        # Si jamais media_jobs n'existe pas, c'est que tables.sql n'a pas été importé.
        # Dans Vodum, on préfère échouer proprement plutôt que créer une version incomplète.
        print("⚠ media_jobs table not found (tables.sql not imported yet). Skipping media_jobs upgrade.")

    # libraries.item_count
    if table_exists(cursor, "libraries") and not column_exists(cursor, "libraries", "item_count"):
        cursor.execute("ALTER TABLE libraries ADD COLUMN item_count INTEGER")
        conn.commit()
        print("✔ libraries.item_count added")

    # media_sessions.library_section_id (pour relier session -> library)
    if table_exists(cursor, "media_sessions") and not column_exists(cursor, "media_sessions", "library_section_id"):
        cursor.execute("ALTER TABLE media_sessions ADD COLUMN library_section_id TEXT")
        conn.commit()
        print("✔ media_sessions.library_section_id added")

    if table_exists(cursor, "media_sessions") and not column_exists(cursor, "media_sessions", "poster_ref_json"):
        cursor.execute("ALTER TABLE media_sessions ADD COLUMN poster_ref_json TEXT")
        conn.commit()
        print("✔ media_sessions.poster_ref_json added")

    if table_exists(cursor, "media_sessions") and not column_exists(cursor, "media_sessions", "backdrop_ref_json"):
        cursor.execute("ALTER TABLE media_sessions ADD COLUMN backdrop_ref_json TEXT")
        conn.commit()
        print("✔ media_sessions.backdrop_ref_json added")

    if table_exists(cursor, "media_sessions") and not column_exists(cursor, "media_sessions", "missing_count"):
        cursor.execute("ALTER TABLE media_sessions ADD COLUMN missing_count INTEGER DEFAULT 0")
        conn.commit()
        print("✔ media_sessions.missing_count added")

    # media_session_history.library_section_id
    if table_exists(cursor, "media_session_history") and not column_exists(cursor, "media_session_history", "library_section_id"):
        cursor.execute("ALTER TABLE media_session_history ADD COLUMN library_section_id TEXT")
        conn.commit()
        print("✔ media_session_history.library_section_id added")

    if table_exists(cursor, "media_session_history") and not column_exists(cursor, "media_session_history", "poster_ref_json"):
        cursor.execute("ALTER TABLE media_session_history ADD COLUMN poster_ref_json TEXT")
        conn.commit()
        print("✔ media_session_history.poster_ref_json added")

    if table_exists(cursor, "media_session_history") and not column_exists(cursor, "media_session_history", "backdrop_ref_json"):
        cursor.execute("ALTER TABLE media_session_history ADD COLUMN backdrop_ref_json TEXT")
        conn.commit()
        print("✔ media_session_history.backdrop_ref_json added")

    # -------------------------------------------------
    # 2.5 Normalize monitoring media_type values (idempotent)
    # -------------------------------------------------
    print("🔧 Normalizing monitoring media_type values…")

    # Harmonise les anciens labels (si tu as déjà stocké series/music/video/etc.)
    # History
    cursor.execute("UPDATE media_session_history SET media_type='serie'  WHERE media_type IN ('series')")
    cursor.execute("UPDATE media_session_history SET media_type='music' WHERE media_type IN ('tracks','track')")

    # "video" historique : on tranche via grandparent_title (épisode si grandparent existe, sinon film)
    cursor.execute("""
        UPDATE media_session_history
        SET media_type='serie'
        WHERE media_type='video'
          AND grandparent_title IS NOT NULL
          AND TRIM(grandparent_title) <> ''
    """)
    cursor.execute("""
        UPDATE media_session_history
        SET media_type='movie'
        WHERE media_type='video'
          AND (grandparent_title IS NULL OR TRIM(grandparent_title) = '')
    """)

    # Live sessions (optionnel mais conseillé pour cohérence UI)
    cursor.execute("UPDATE media_sessions SET media_type='serie'  WHERE media_type IN ('series')")
    cursor.execute("UPDATE media_sessions SET media_type='tracks' WHERE media_type IN ('music','track')")
    cursor.execute("""
        UPDATE media_sessions
        SET media_type='serie'
        WHERE media_type='video'
          AND grandparent_title IS NOT NULL
          AND TRIM(grandparent_title) <> ''
    """)
    cursor.execute("""
        UPDATE media_sessions
        SET media_type='movie'
        WHERE media_type='video'
          AND (grandparent_title IS NULL OR TRIM(grandparent_title) = '')
    """)

    conn.commit()
    print("✔ Monitoring media_type normalized.")

    # -------------------------------------------------
    # 2.6 Server deletion performance indexes
    # -------------------------------------------------
    cursor.execute("DROP INDEX IF EXISTS uq_media_users_vodum_server")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vodum_users_status ON vodum_users(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vodum_users_status_expiration ON vodum_users(status, expiration_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vodum_users_expiration_date ON vodum_users(expiration_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vodum_users_subscription_template ON vodum_users(subscription_template_id)")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_users_vodum_server
        ON media_users(vodum_user_id, server_id)
        WHERE vodum_user_id IS NOT NULL
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_users_server ON media_users(server_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_users_vodum_user ON media_users(vodum_user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_libraries_server ON libraries(server_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_user_libraries_library ON media_user_libraries(library_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_identities_server ON user_identities(server_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_welcome_email_templates_server ON welcome_email_templates(server_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_enforcement_state_server ON stream_enforcement_state(server_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_enforcements_server ON stream_enforcements(server_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_server_library_stopped ON media_session_history(server_id, library_section_id, stopped_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_library_top_played ON media_session_history(server_id, library_section_id, media_key, started_at, stopped_at)")
    conn.commit()

    print("✔ Server deletion performance indexes verified.")


    # -------------------------------------------------
    # 3. Injecter les données par défaut
    # -------------------------------------------------

    # Tâche sync_plex
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "sync_plex",
        "description": "task_description.sync_plex",
        "schedule": "0 */6 * * *",  # toutes les 6h
        "enabled": 0,
        "status": "disabled"
    })



    # Tâche cleanup_logs (suppression logs > 7 jours)
    #ensure_row(cursor, "tasks", "name = :name", {
    #    "name": "cleanup_logs",
    #    "description": "Suppression automatique des logs de plus de 7 jours",
    #    "schedule": "0 2 * * *",  # tous les jours à 02h00
    #    "enabled": 1,
    #    "status": "idle"
    #})

    # Tâche check_update (tous les jours)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_update",
        "description": "task_description.check_update",
        "schedule": "0 4 * * *",  # tous les jours à 04:00
        "enabled": 1,
        "status": "idle"
    })


    # Tâche backup automatique (tous les 3 jours à 03:00)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "auto_backup",
        "description": "task_description.auto_backup",
        "schedule": "0 3 */3 * *",   # tous les 3 jours
        "enabled": 1,
        "status": "idle"
    })

    # Restore backup (ON-DEMAND)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "restore_backup",
        "description": "task_description.restore_backup",
        "schedule": None,
        "enabled": 1,
        "status": "idle"
    })

    # Tâche cleanup des backups (supprime backups > 30 jours)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_backups",
        "description": "task_description.cleanup_backups",
        "schedule": "30 3 * * *",  # tous les jours à 03:30
        "enabled": 1,
        "status": "idle"
    })

    # Tâche cleanup des données (purge des historiques selon data_retention_years)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_data_retention",
        "description": "task_description.cleanup_data_retention",
        "schedule": "0 4 * * 0",  # chaque dimanche à 04:00
        "enabled": 1,
        "status": "idle"
    })

    # Tâche vérification intégrité DB
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "db_integrity_check",
        "description": "task_description.db_integrity_check",
        "schedule": "15 4 * * 0",  # chaque dimanche à 04:15
        "enabled": 1,
        "status": "idle"
    })

    # Tâche cleanup du cache artwork (posters/backdrops monitoring)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_artwork_cache",
        "description": "task_description.cleanup_artwork_cache",
        "schedule": "30 4 * * 0",  # chaque dimanche à 04:30
        "enabled": 1,
        "status": "idle"
    })

    # Tâche warmup du cache artwork (posters/backdrops monitoring)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "warmup_artwork_cache",
        "description": "task_description.warmup_artwork_cache",
        "schedule": "*/30 * * * *",  # toutes les 30 minutes
        "enabled": 1,
        "status": "idle"
    })

    # Tâche update_user_status
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "update_user_status",
        "description": "task_description.update_user_status",
        "schedule": "0 * * * *",  # Toutes les heures
        "enabled": 1,
        "status": "idle"
    })

    # Tâche check_servers (ping léger des serveurs toutes les 10 minutes)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_servers",
        "description": "task_description.check_servers",
        "schedule": "*/30 * * * *",  # toutes les 30 minutes
        "enabled": 1,
        "status": "idle"
    })

    # Tâche daily_unfriend_cleanup
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_unfriended",
        "description": "task_description.cleanup_unfriended",
        "schedule": "0 4 * * *",  # tous les jours à 04h00
        "enabled": 1,
        "status": "idle"
    })

    # Scheduler monitoring (enqueue)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "monitor_enqueue_refresh",
        "description": "task_description.monitor_enqueue_refresh",
        "schedule": "*/3 * * * *",
        "enabled": 1,
        "status": "idle"
    })

    # Worker queue
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "media_jobs_worker",
        "description": "task_description.media_jobs_worker",
        "schedule": "*/1 * * * *",
        "enabled": 1,
        "status": "idle"
    })

    cursor.execute("""
        UPDATE tasks
        SET enabled = 1,
            status = CASE
                WHEN status = 'disabled' THEN 'idle'
                ELSE status
            END
         
        WHERE name IN ('monitor_enqueue_refresh', 'media_jobs_worker')
    """)

    # Tautulli import (ON-DEMAND)
    # - No cron schedule: it is launched manually when a Tautulli DB is uploaded.
    # - Keeping enabled=1 allows run_task_by_name('import_tautulli') to enqueue it.
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "import_tautulli",
        "description": "task_description.import_tautulli",
        "schedule": None,
        "enabled": 1,
        "status": "idle"
    })
    # --- FORCE import_tautulli en ON-DEMAND (pas de cron) ---
    cursor.execute("""
        UPDATE tasks
        SET
            schedule = NULL,
            next_run  = NULL,
            enabled   = 1,
            status    = CASE
                          WHEN status = 'running' THEN status
                          ELSE 'idle'
                        END,
            updated_at = CURRENT_TIMESTAMP
        WHERE name = 'import_tautulli'
    """)
    conn.commit()

    # Ajouter la tâche send_expiration_emails si absente
    cursor.execute("""
        SELECT 1 FROM tasks WHERE name = 'send_expiration_emails'
    """)
    exists = cursor.fetchone()

    if not exists:
        cursor.execute("""
            INSERT INTO tasks (name, schedule, enabled, status)
            VALUES ('send_expiration_emails', '0 * * * *', 0, 'disabled')
        """)
        print("➕ Task send_expiration_emails added.")

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_pending_invite_reminders",
        "description": "task_description.send_pending_invite_reminders",
        "schedule": "30 0 * * *",
        "enabled": 1,
        "status": "idle"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_telemetry",
        "description": "Send anonymous Vodum telemetry statistics.",
        "schedule": "0 * * * *",
        "enabled": 1,
        "status": "idle"
    })

    # Ajouter les tâches Discord si absentes
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_expiration_discord",
        "description": "task_description.send_expiration_discord",
        "schedule": "0 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_campaign_discord",
        "description": "task_description.send_campaign_discord",
        "schedule": "*/10 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_comm_campaigns",
        "description": "task_description.send_comm_campaigns",
        "schedule": "*/10 * * * *",
        "enabled": 0,
        "status": "disabled"
    })



    # -------------------------------------------------
    # MASTER enable_cron_jobs enforcement
    # If scheduled tasks are globally disabled, we force-disable any enabled task
    # that could have been inserted by migrations / new code.
    # -------------------------------------------------
    try:
        cursor.execute("SELECT enable_cron_jobs FROM settings WHERE id = 1")
        row = cursor.fetchone()
        cron_enabled = int(row[0]) if row and row[0] is not None else 1
    except Exception:
        cron_enabled = 1

    if cron_enabled == 0:
        cursor.execute(
            '''
            UPDATE tasks
            SET
                enabled_prev = CASE
                    WHEN enabled_prev IS NULL THEN enabled
                    ELSE enabled_prev
                END,
                enabled = 0,
                status = 'disabled',
                updated_at = CURRENT_TIMESTAMP
            '''
        )
        conn.commit()
        print("✔ Cron disabled: all tasks forced to disabled (state remembered).")


    # -------------------------------------------------
    # 3.1 Seed default welcome templates (English)
    # -------------------------------------------------
    def ensure_welcome_template(provider, server_id, subject, body):
        cursor.execute(
            "SELECT 1 FROM welcome_email_templates WHERE provider=? AND server_id IS ?",
            (provider, server_id),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO welcome_email_templates(provider, server_id, subject, body)
                VALUES (?, ?, ?, ?)
                """,
                (provider, server_id, subject, body),
            )
            print(f"➕ Default welcome template inserted: {provider} / server_id={server_id}")

    plex_subject = "Welcome to Plex - {server_name}"
    plex_body = """Hi {firstname} {lastname},

    You've been invited to access our Plex server.

    1) Create (or sign in to) your Plex account using this email: {email}
    2) Accept the invitation from Plex
    3) Open the server and start watching

    Server name: {server_name}

    Need help?
    - Install Plex on your device (TV / mobile / web)
    - Sign in with your Plex account
    - Accept the share invitation
    - You will then see the server in your Plex home

    Regards,
    {brand_name}
    """

    jf_subject = "Welcome to Jellyfin - {server_name}"
    jf_body = """Hi {firstname} {lastname},

    Your Jellyfin account is ready.

    Server: {server_name}
    URL: {server_url}
    Username: {login_username}
    Temporary password: {temporary_password}

    How to log in:
    - Open the URL above (web)
    - Or install the Jellyfin app (Android / iOS / TV)
    - Sign in with your username and password

    Regards,
    {brand_name}
    """

    ensure_welcome_template("plex", None, plex_subject, plex_body)
    ensure_welcome_template("jellyfin", None, jf_subject, jf_body)

    conn.commit()

    # -------------------------------------------------
    # 3.2 Seed default COMM templates once
    # -------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_template_seed_state (
            seed_key TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    default_comm_templates = [
        {
            "key": "default_expiration_date_change",
            "name": "Expiration date change",
            "enabled": 0,
            "trigger_event": "expiration_change",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": None,
            "days_after": 0,
            "subject": "Your subscription date has been updated",
            "body": (
                "Hello {username},\n\n"
                "Your subscription expiration date has been updated.\n\n"
                "Previous expiration date: {old_expiration_date}\n"
                "New expiration date: {new_expiration_date}\n"
                "Change: {expiration_change_signed_days} day(s)\n"
                "Reason: {expiration_change_reason}\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
        {
            "key": "default_fin",
            "name": "Expired subscription",
            "enabled": 0,
            "trigger_event": "expiration",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": 0,
            "days_after": None,
            "subject": "Your subscription has expired",
            "body": (
                "Hello {username},\n\n"
                "Your subscription expired on {expiration_date}.\n"
                "Your access may now be suspended.\n\n"
                "If you wish to continue using the service, please renew your subscription.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
        {
            "key": "default_pending_invite_reminder",
            "name": "Pending invite reminder",
            "enabled": 0,
            "trigger_event": "pending_invite_reminder",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": None,
            "days_after": 3,
            "subject": "Reminder - please accept your invitation",
            "body": (
                "Hello {username},\n\n"
                "Your invitation is still waiting for acceptance.\n\n"
                "To start using your account:\n"
                "- Open Plex or Jellyfin\n"
                "- Sign in with your account\n"
                "- Accept the library share invitation if prompted\n\n"
                "Your subscription expiration is currently set to: {expiration_date}\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
        {
            "key": "default_preavis",
            "name": "Expiration notice",
            "enabled": 0,
            "trigger_event": "expiration",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": 30,
            "days_after": None,
            "subject": "Your subscription will expire in {days_left} days",
            "body": (
                "Hello {username},\n\n"
                "Your subscription will expire in {days_left} days.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Please renew it to avoid any service interruption.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
        {
            "key": "default_parrainage",
            "name": "Referral reward",
            "enabled": 0,
            "trigger_event": "referral_reward",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": None,
            "days_after": 0,
            "subject": "Referral reward granted",
            "body": (
                "Hello {username},\n\n"
                "Good news: you earned {referral_reward_days} bonus day(s) thanks to {referred_username}.\n\n"
                "Previous expiration date: {referrer_old_expiration_date}\n"
                "New expiration date: {referrer_new_expiration_date}\n\n"
                "Thank you for your referral.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
        {
            "key": "default_relance",
            "name": "Expiration reminder",
            "enabled": 0,
            "trigger_event": "expiration",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": 7,
            "days_after": None,
            "subject": "Reminder - your subscription will expire soon",
            "body": (
                "Hello {username},\n\n"
                "This is a friendly reminder that your subscription will expire in {days_left} days.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Please renew it in time to avoid any service interruption.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
        {
            "key": "default_user_creation",
            "name": "User creation",
            "enabled": 0,
            "trigger_event": "user_creation",
            "trigger_provider": "all",
            "subscription_scope": "all",
            "subscription_template_id": None,
            "expiration_change_direction": "all",
            "days_before": None,
            "days_after": 0,
            "subject": "Welcome - your account is ready",
            "body": (
                "Hello {username},\n\n"
                "Your account has been created successfully.\n\n"
                "Login email: {email}\n\n"
                "How to get started:\n"
                "- Open Plex or Jellyfin\n"
                "- Sign in with your account\n"
                "- Accept the library share invitation if prompted\n\n"
                "Subscription expiration date: {expiration_date}\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
    ]

    cursor.execute(
        "SELECT seed_key FROM comm_template_seed_state WHERE seed_key = ?",
        ("default_comm_templates",),
    )
    default_comm_templates_already_seeded = cursor.fetchone() is not None

    if not default_comm_templates_already_seeded:
        print("🛠 Checking bundled default communication templates")

        inserted_defaults = 0

        for tpl in default_comm_templates:
            cursor.execute(
                "SELECT id FROM comm_templates WHERE key = ?",
                (tpl["key"],),
            )

            if cursor.fetchone():
                continue

            cursor.execute(
                """
                INSERT INTO comm_templates(
                    key,
                    name,
                    enabled,
                    trigger_event,
                    trigger_provider,
                    expiration_change_direction,
                    subscription_scope,
                    subscription_template_id,
                    days_before,
                    days_after,
                    subject,
                    body,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    tpl["key"],
                    tpl["name"],
                    tpl["enabled"],
                    tpl["trigger_event"],
                    tpl["trigger_provider"],
                    tpl["expiration_change_direction"],
                    tpl["subscription_scope"],
                    tpl["subscription_template_id"],
                    tpl["days_before"],
                    tpl["days_after"],
                    tpl["subject"],
                    tpl["body"],
                ),
            )
            inserted_defaults += 1

        cursor.execute(
            "INSERT OR IGNORE INTO comm_template_seed_state(seed_key) VALUES (?)",
            ("default_comm_templates",),
        )
        conn.commit()

        print(f"✔ Bundled default communication templates inserted: {inserted_defaults}")

    # -------------------------------------------------
    # 4. Templates email par défaut 
    # -------------------------------------------------

    DEFAULT_TEMPLATES = {
        "preavis": {
            "subject": "Your subscription will expire soon",
            "body": (
                "Hello {username},\n\n"
                "Your subscription will expire in {days_left} days.\n"
                "Please renew it to avoid any service interruption.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Best regards,\n"
                "The {brand_name}"
            )
        },
        "relance": {
            "subject": "Reminder: Your subscription is about to expire",
            "body": (
                "Hello {username},\n\n"
                "This is a friendly reminder that your subscription will expire in {days_left} days.\n"
                "Don't forget to renew it in time.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Best regards,\n"
                "The {brand_name}"
            )
        },
        "fin": {
            "subject": "Your subscription has expired",
            "body": (
                "Hello {username},\n\n"
                "Your subscription expired on {expiration_date}.\n"
                "Your access has now been suspended.\n\n"
                "If you wish to continue using our services, you can renew your subscription at any time.\n\n"
                "Best regards,\n"
                "The {brand_name}"
            )
        }
    }

    for tpl_type, tpl_data in DEFAULT_TEMPLATES.items():

        # Vérifier existence du template
        cursor.execute(
            "SELECT COUNT(*) FROM email_templates WHERE type = ?",
            (tpl_type,)
        )
        exists = cursor.fetchone()[0]

        # Si inexistant → créer avec valeurs par défaut
        if exists == 0:
            print(f"➕ Ajout du template email par défaut : {tpl_type}")

            cursor.execute(
                """
                INSERT INTO email_templates (type, subject, body, days_before)
                VALUES (?, ?, ?, ?)
                """,
                (
                    tpl_type,
                    tpl_data["subject"],
                    tpl_data["body"],
                    30 if tpl_type == "preavis"
                    else 7 if tpl_type == "relance"
                    else 0

                ),
            )

        else:
            # Si existant → vérifier s'il manque subject / body
            cursor.execute(
                "SELECT subject, body FROM email_templates WHERE type = ?",
                (tpl_type,)
            )
            row = cursor.fetchone()

            # row est un tuple, pas un Row → utiliser indices
            subject = row[0] if row else ""
            body = row[1] if row else ""

            if not subject or not body:
                print(f"🛠 Updating empty email template : {tpl_type}")
                cursor.execute(
                    """
                    UPDATE email_templates
                    SET subject = CASE WHEN subject='' OR subject IS NULL THEN ? ELSE subject END,
                        body    = CASE WHEN body='' OR body IS NULL THEN ? ELSE body END
                    WHERE type = ?
                    """,
                    (
                        tpl_data["subject"],
                        tpl_data["body"],
                        tpl_type
                    )
                )

    # Tâche d'envoi des campagnes email
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_mail_campaigns",
        "description": "task_description.send_mail_campaigns",
        "schedule": "*/15 * * * *",  # toutes les 15 minutes
        "enabled": 0,
        "status": "disabled"
    })

    # Tâche check_mailing_status : active/désactive automatiquement les tâches Email/Discord
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_mailing_status",
        "description": "task_description.check_mailing_status",
        "schedule": "0 * * * *",  # toutes les 5 minutes
        "enabled": 1,
        "status": "idle"
    })


    # Tâche stream_enforcer 
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "stream_enforcer",
        "description": "task_description.stream_enforcer",
        "schedule": "*/2 * * * *",   # toutes les 2 minutes
        "enabled": 0,                
        "status": "disabled"
    })

    # Tâche apply_plex_access_updates (pour appliquer les jobs Plex)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_plex_access_updates",
        "description": "task_description.apply_plex_access_updates",
        "schedule": "*/5 * * * *",   # toutes les 5 minutes
        "enabled": 0,                # activée uniquement quand un job est ajouté
        "status": "idle"
    })

    # Tâche sync_Jellyfin
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "sync_jellyfin",
        "description": "task_description.sync_jellyfin",
        "schedule": "0 */6 * * *",  # toutes les 6 heures (comme Plex)
        "enabled": 0,
        "status": "disabled"
    })

    # Tâche disable_expired_users (désactivation des accès Plex à l'expiration)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "disable_expired_users",
        "description": "task_description.disable_expired_users",
        "schedule": "0 */12 * * *",  # toutes les 12 heures
        "enabled": 0,                # pilotée par settings.disable_on_expiry
        "status": "idle"
    })
    # Tâche expired_subscription_manager (policy "abonnement expiré" + disable différé)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "expired_subscription_manager",
        "description": "task_description.expired_subscription_manager",
        "schedule": "0 */1 * * *",  # toutes les heures
        "enabled": 0,               # pilotée par settings.expiry_mode
        "status": "disabled"
    })



    # Tâche apply_jellyfin_access_updates (désactivation des accès Jellyfin à l'expiration)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_jellyfin_access_updates",
        "description": "task_description.apply_jellyfin_access_updates",
        "schedule": "*/5 * * * *",   # toutes les 5 minutes
        "enabled": 0,
        "status": "idle"
    })

    # Tâche legacy monitor_collect_sessions
    #
    # Cette ancienne tâche collecte tous les serveurs en direct.
    # Elle ne doit plus tourner avec le nouveau pipeline :
    # monitor_enqueue_refresh -> media_jobs_worker -> collect_sessions_for_server.
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "monitor_collect_sessions",
        "description": "task_description.monitor_collect_sessions",
        "schedule": None,
        "enabled": 0,
        "status": "disabled"
    })

    cursor.execute("""
        UPDATE tasks
        SET enabled = 0,
            status = 'disabled',
            schedule = NULL,
            queued_count = 0,
            next_run = NULL
        WHERE name = 'monitor_collect_sessions'
    """)

    # Tâche refresh_dashboard_quote_cache (quote du jour du dashboard)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "refresh_dashboard_quote_cache",
        "description": "task_description.refresh_dashboard_quote_cache",
        "schedule": "*/3 * * * *",   # vérifie toutes les 3h, mais ne recalcule qu'une fois par jour
        "enabled": 1,
        "status": "idle"
    })

    # Auto-réparation :
    # si la tâche existe déjà mais est restée désactivée sur une ancienne base,
    # on la remet ON uniquement si elle n'a encore jamais tourné.
    cursor.execute(
        """
        UPDATE tasks
        SET
            enabled = 1,
            status = 'idle',
            updated_at = CURRENT_TIMESTAMP
        WHERE name = 'refresh_dashboard_quote_cache'
          AND COALESCE(enabled, 0) = 0
          AND last_run IS NULL
        """
    )

    # Tâche referral rewards
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "process_referral_rewards",
        "description": "task_description.process_referral_rewards",
        "schedule": "15 2 * * *",
        "enabled": 1,
        "status": "idle",
    })
    # Tâche referral_cleanup
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "referral_cleanup",
        "description": "task_description.referral_cleanup",
        "schedule": "0 12 * * *",
        "enabled": 1,
        "status": "idle"
    })
    conn.commit()

    # -------------------------------------------------
    # Paramètres de base (settings)
    # -------------------------------------------------

    ensure_row(cursor, "settings", "id = :id", {
        "id": 1,
        "mail_from": "noreply@example.com",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_tls": 1,
        "smtp_user": "",
        "smtp_pass": "",
        "skip_never_used_accounts": 0,

        # ⛔ NE PAS FORCER LA LANGUE
        "default_language": None,

        "timezone": "Europe/Paris",
        "admin_email": "",
        "enable_cron_jobs": 1,
        "default_expiration_days": 90,
        "maintenance_mode": 0,
        "brand_name": None,
        "debug_mode": 0,
        "admin_password_hash": None,
        "auth_enabled": 1,
        "web_secure_cookies": 0,
        "web_cookie_samesite": "Lax",
        "web_trust_proxy": 0,
    })

    # -------------------------------------------------
    # 3.x Versioned task schedule defaults migration
    # -------------------------------------------------
    # ensure_row() only inserts missing tasks.
    # This migration updates existing installs when Vodum changes default schedules,
    # without overwriting admin-customized schedules.
    TASK_DEFAULTS_VERSION = 2

    TASK_SCHEDULE_DEFAULTS = {
        "sync_plex": "0 */6 * * *",
        "check_update": "0 4 * * *",
        "auto_backup": "0 3 */3 * *",
        "cleanup_backups": "30 3 * * *",
        "cleanup_data_retention": "0 4 * * 0",
        "db_integrity_check": "15 4 * * 0",
        "cleanup_artwork_cache": "30 4 * * 0",
        "warmup_artwork_cache": "*/30 * * * *",
        "update_user_status": "0 * * * *",
        "check_servers": "*/30 * * * *",
        "cleanup_unfriended": "0 4 * * *",
        "monitor_enqueue_refresh": "*/1 * * * *",
        "media_jobs_worker": "*/1 * * * *",
        "send_pending_invite_reminders": "30 0 * * *",
        "send_telemetry": "0 * * * *",
        "send_expiration_emails": "0 * * * *",
        "send_expiration_discord": "0 * * * *",
        "send_campaign_discord": "*/10 * * * *",
        "send_comm_campaigns": "*/10 * * * *",
    }

    TASK_SCHEDULE_LEGACY_DEFAULTS = {
        "monitor_enqueue_refresh": {"*/3 * * * *", "*/1 * * * *"},
        "media_jobs_worker": {"*/1 * * * *"},
        "check_servers": {"*/10 * * * *", "*/30 * * * *"},
        "send_pending_invite_reminders": {"0 30 * * *", "30 * * *", "30 0 * * *"},
        "send_telemetry": {"0 0 * * *", "0 * * * *"},
    }

    cursor.execute("SELECT COALESCE(task_defaults_version, 0) FROM settings WHERE id = 1")
    row = cursor.fetchone()
    current_task_defaults_version = int(row[0]) if row and row[0] is not None else 0

    if current_task_defaults_version < TASK_DEFAULTS_VERSION:
        print(f"🔧 Applying task schedule defaults migration v{TASK_DEFAULTS_VERSION}…")

        for task_name, new_schedule in TASK_SCHEDULE_DEFAULTS.items():
            cursor.execute(
                "SELECT schedule FROM tasks WHERE name = ?",
                (task_name,),
            )
            task_row = cursor.fetchone()
            if not task_row:
                continue

            current_schedule = task_row[0]

            allowed_legacy_schedules = TASK_SCHEDULE_LEGACY_DEFAULTS.get(task_name, {new_schedule})

            if current_schedule in allowed_legacy_schedules:
                cursor.execute(
                    """
                    UPDATE tasks
                    SET schedule = ?,
                        next_run = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE name = ?
                    """,
                    (new_schedule, task_name),
                )
                print(f"✔ Task schedule updated: {task_name} -> {new_schedule}")
            else:
                print(f"↪ Task schedule kept unchanged (custom): {task_name} -> {current_schedule}")

        cursor.execute(
            """
            UPDATE settings
            SET task_defaults_version = ?
            WHERE id = 1
            """,
            (TASK_DEFAULTS_VERSION,),
        )
        conn.commit()


    conn.commit()
    conn.close()

    print("✔ Migrations completed successfully !")



if __name__ == "__main__":
    run_migrations()
    #ensure_settings_defaults(cursor)

