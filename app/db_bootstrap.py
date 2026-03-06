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
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(policy_id) REFERENCES stream_policies(id) ON DELETE CASCADE,
          FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_enforcements_time ON stream_enforcements(created_at);")
        conn.commit()

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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_snapshots_ts ON monitoring_snapshots(ts);")
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

    # 1.2 vodum_users per-user stream override (NEW)
    ensure_column(cursor, "vodum_users", "max_streams_override", "INTEGER DEFAULT NULL")
    ensure_column(cursor, "vodum_users", "notifications_order_override", "TEXT DEFAULT NULL")
    # Subscription template assignment (NEW)
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
          policies_json TEXT NOT NULL DEFAULT '[]',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

    # Ensure at least one default template (EN), deletable/modifiable
    try:
        cursor.execute("SELECT COUNT(*) FROM subscription_templates")
        cnt = int(cursor.fetchone()[0] or 0)
    except Exception:
        cnt = 0

    if cnt == 0:
        print("🛠 Creating default subscription template: Default")
        cursor.execute(
            "INSERT INTO subscription_templates(name, notes, policies_json) VALUES (?, ?, ?)",
            (
                "Default",
                "Base template with no restrictions. Edit or delete if you want.",
                "[]",
            ),
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


    
    # 🔐 Auth admin
    ensure_column(cursor, "settings", "admin_password_hash", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "auth_enabled", "INTEGER DEFAULT 1")
    
    print("✔ Settings columns verified (brand_name).")
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

    # ✅ IMPORTANT: these columns MUST be ensured even if the table already exists
    ensure_column(
        cursor,
        "comm_templates",
        "trigger_event",
        "TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation'))",
    )
    ensure_column(
        cursor,
        "comm_templates",
        "trigger_provider",
        "TEXT NOT NULL DEFAULT 'all' CHECK(trigger_provider IN ('all','plex','jellyfin'))",
    )
    ensure_column(cursor, "comm_templates", "days_after", "INTEGER DEFAULT NULL")
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

    if not table_exists(cursor, "comm_history"):
        print("🛠 Creating table: comm_history")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('template','campaign')),
            template_id INTEGER NULL,
            campaign_id INTEGER NULL,
            user_id INTEGER NULL,
            channel_used TEXT NOT NULL CHECK(channel_used IN ('email','discord')),
            status TEXT NOT NULL CHECK(status IN ('sent','failed')),
            error TEXT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            meta_json TEXT NULL,
            FOREIGN KEY(template_id) REFERENCES comm_templates(id) ON DELETE SET NULL,
            FOREIGN KEY(campaign_id) REFERENCES comm_campaigns(id) ON DELETE SET NULL,
            FOREIGN KEY(user_id) REFERENCES vodum_users(id) ON DELETE SET NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_history_sent_at ON comm_history(sent_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_history_user ON comm_history(user_id, sent_at DESC);")
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
    # media_sessions: garantir l'unicité requise par
    # ON CONFLICT(server_id, session_key)
    # -------------------------------------------------

    # Nettoyage des doublons éventuels avant création de l'index unique
    cursor.execute("""
        DELETE FROM media_sessions
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM media_sessions
            GROUP BY server_id, session_key
        )
    """)

    # IMPORTANT:
    # le collector utilise:
    #   ON CONFLICT(server_id, session_key) DO UPDATE
    # donc il faut absolument une contrainte unique équivalente
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_media_sessions_server_session
        ON media_sessions(server_id, session_key)
    """)

    # Index classiques
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

    # -------------------------------------------------
    # UNIQUE session key dedup (1 playback = 1 session_key)
    # -------------------------------------------------
    # 1) Nettoyage : si ta DB contient déjà des doublons (server_id, session_key),
    # on garde la plus ancienne ligne (MIN(id)) et on supprime les autres.
    cursor.execute("""
        DELETE FROM media_session_history
        WHERE TRIM(COALESCE(session_key,'')) <> ''
          AND id NOT IN (
            SELECT MIN(id)
            FROM media_session_history
            WHERE TRIM(COALESCE(session_key,'')) <> ''
            GROUP BY server_id, session_key
          )
    """)

    # 2) Index unique : permet au ON CONFLICT(server_id, session_key) de fonctionner
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_session
        ON media_session_history (server_id, session_key)
        WHERE TRIM(COALESCE(session_key,'')) <> ''
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

    # media_session_history.library_section_id
    if table_exists(cursor, "media_session_history") and not column_exists(cursor, "media_session_history", "library_section_id"):
        cursor.execute("ALTER TABLE media_session_history ADD COLUMN library_section_id TEXT")
        conn.commit()
        print("✔ media_session_history.library_section_id added")

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
        "schedule": "*/1 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

    # Worker queue
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "media_jobs_worker",
        "description": "task_description.media_jobs_worker",
        "schedule": "*/1 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

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
    Vodum Team
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
    Vodum Team
    """

    ensure_welcome_template("plex", None, plex_subject, plex_body)
    ensure_welcome_template("jellyfin", None, jf_subject, jf_body)

    conn.commit()

    # -------------------------------------------------
    # 3.2 Seed default COMM template: user_creation (EMAIL ONLY)
    # -------------------------------------------------
    def ensure_comm_user_creation_template():
        # Create ONE default template used by the new "user_creation" trigger.
        # Notes:
        # - Email only is enforced in users.py (discord_user_id=None)
        # - Placeholders supported by current code: {username} {email} {expiration_date}
        key = "user_creation_default"
        cursor.execute("SELECT 1 FROM comm_templates WHERE key = ?", (key,))
        if cursor.fetchone():
            return

        subject = "Welcome - your account is ready"
        body = (
            "Hi {username},\n\n"
            "Your account has been created successfully.\n"
            "Login email: {email}\n\n"
            "How to get started:\n"
            "- Open the Plex/Jellyfin app (TV / mobile / web)\n"
            "- Sign in with your account\n"
            "- If this is Plex: accept the share invitation if prompted\n\n"
            "Subscription expiry date: {expiration_date}\n\n"
            "Regards,\n"
            "VODUM Team\n"
        )

        cursor.execute(
            """
            INSERT INTO comm_templates(
                key, name, enabled,
                trigger_event, trigger_provider,
                days_before, days_after,
                subject, body,
                created_at, updated_at
            )
            VALUES(
                ?, ?, 1,
                'user_creation', 'all',
                NULL, 0,
                ?, ?,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (key, "Default - User creation", subject, body),
        )
        print("➕ Default comm_template inserted: user_creation_default (trigger=user_creation)")

    ensure_comm_user_creation_template()
    conn.commit()

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
                "The VODUM Team"
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
                "The VODUM Team"
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
                "The VODUM Team"
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
        "schedule": "*/5 * * * *",  # toutes les 5 minutes
        "enabled": 0,
        "status": "disabled"
    })

    # Tâche check_mailing_status : active/désactive automatiquement les tâches Email/Discord
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_mailing_status",
        "description": "task_description.check_mailing_status",
        "schedule": "*/5 * * * *",  # toutes les 5 minutes
        "enabled": 1,
        "status": "idle"
    })


    # Tâche stream_enforcer 
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "stream_enforcer",
        "description": "task_description.stream_enforcer",
        "schedule": "*/1 * * * *",   # toutes les 1 minutes
        "enabled": 0,                
        "status": "disabled"
    })

    # Tâche apply_plex_access_updates (pour appliquer les jobs Plex)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_plex_access_updates",
        "description": "task_description.apply_plex_access_updates",
        "schedule": "*/2 * * * *",   # toutes les 2 minutes
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
        "schedule": "*/2 * * * *",   # toutes les 2 minutes
        "enabled": 0,
        "status": "idle"
    })

    # Tâche monitor_collect_sessions (Now Playing multi-serveurs)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "monitor_collect_sessions",
        "description": "task_description.monitor_collect_sessions",
        "schedule": "*/1 * * * *",   # toutes les minutes (safe pour débuter)
        "enabled": 0,                # tu l’activeras via UI quand prêt
        "status": "disabled"
    })



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
    })




    conn.commit()
    conn.close()

    print("✔ Migrations completed successfully !")



if __name__ == "__main__":
    run_migrations()
    #ensure_settings_defaults(cursor)

