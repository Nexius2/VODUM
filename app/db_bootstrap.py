import sqlite3
import os

DB_PATH = "/appdata/database.db"

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
        "tasks": []
    }


    for table in REQUIRED_TABLES:
        if not table_exists(cursor, table):
            raise RuntimeError(f"❌ ERROR: table '{table}' does not exist ! "
                               f"-> Check that tables.sql has been imported correctly.")

    print("✔ All tables exist.")

    # -------------------------------------------------
    # 2. Vérifier que toutes les colonnes obligatoires existent
    # -------------------------------------------------

    TASK_COLUMNS = {
        "name": "TEXT UNIQUE NOT NULL",
        "description": "TEXT",
        "schedule": "TEXT",
        "enabled": "INTEGER DEFAULT 1",
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

    
    # 🔐 Auth admin
    ensure_column(cursor, "settings", "admin_password_hash", "TEXT DEFAULT NULL")
    ensure_column(cursor, "settings", "auth_enabled", "INTEGER DEFAULT 1")
    
    print("✔ Settings columns verified (brand_name).")

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
    cursor.execute("UPDATE media_session_history SET media_type='tracks' WHERE media_type IN ('music','track')")

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

    # Tâche check_mailing_status : vérifie chaque heure l'activation du mailing
    #ensure_row(cursor, "tasks", "name = :name", {
    #    "name": "check_mailing_status",
    #    "description": "Vérifie le paramètre mailing_enabled et active/désactive les tâches d'envoi",
    #    "schedule": "*/5 * * * *",  # toutes les 5 minutes
    #    "enabled": 1,
    #    "status": "idle"
    #})

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

