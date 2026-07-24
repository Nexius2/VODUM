def ensure_communications_schema(conn, cursor, *, table_exists, ensure_column) -> None:
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
            trigger_event TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked','usage_risk_upgrade_suggestion')),
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
        "TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked','usage_risk_upgrade_suggestion'))",
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

    if not table_exists(cursor, "comm_template_translations"):
        print("Creating table: comm_template_translations")
        cursor.execute("""
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
        """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_template_translations_template ON comm_template_translations(template_id, language)")
    cursor.execute("""
        INSERT OR IGNORE INTO comm_template_translations(template_id, language, subject, body)
        SELECT
            id,
            COALESCE(NULLIF(TRIM((SELECT communication_language FROM settings WHERE id = 1)), ''), 'en'),
            subject,
            body
        FROM comm_templates
        WHERE COALESCE(subject, '') <> ''
          AND COALESCE(body, '') <> ''
    """)
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
        if "'usage_risk_upgrade_suggestion'" not in sql:
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
            trigger_event TEXT NOT NULL DEFAULT 'expiration' CHECK(trigger_event IN ('expiration','user_creation','pending_invite_reminder','referral_reward','expiration_change','stream_blocked','usage_risk_upgrade_suggestion')),
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
        "Stream killed: {stream_killed}\n"
        "Rule usage: {policy_observed} / {policy_limit}\n"
        "Other active streams ({other_streams_count}):\n"
        "{other_streams}\n"
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
    ensure_column(cursor, "comm_scheduled", "catchup_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(cursor, "comm_scheduled", "last_catchup_at", "TIMESTAMP DEFAULT NULL")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_retry ON comm_scheduled(status, next_attempt_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_catchup ON comm_scheduled(status, catchup_count, last_catchup_at)")
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
            catchup_count INTEGER NOT NULL DEFAULT 0,
            last_catchup_at TIMESTAMP DEFAULT NULL,
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
            payload_json, dedupe_key, channels_sent,
            catchup_count, last_catchup_at
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
            channels_sent,
            COALESCE(catchup_count, 0),
            last_catchup_at
        FROM comm_scheduled_old
        """)

        cursor.execute("DROP TABLE comm_scheduled_old")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_due ON comm_scheduled(status, send_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_user ON comm_scheduled(vodum_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_retry ON comm_scheduled(status, next_attempt_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comm_scheduled_catchup ON comm_scheduled(status, catchup_count, last_catchup_at)")
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
            print("?? Migrating templates: email_templates + discord_templates ? comm_templates")

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
            print("?? Migrating campaigns: mail_campaigns + discord_campaigns ? comm_campaigns")

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
                print("?? Migrating history: sent_emails ? comm_history")
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
                print("?? Migrating history: sent_discord ? comm_history")
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
        print(f"âš ï¸ Communications migration skipped: {e}")

