from __future__ import annotations


def ensure_portal_foundation_schema(conn, cursor, *, table_exists, ensure_column):
    """Create the disabled-by-default user portal authentication foundation."""
    for column, definition in {
        "portal_enabled": "INTEGER NOT NULL DEFAULT 0",
        "portal_local_test_enabled": "INTEGER NOT NULL DEFAULT 0",
        "portal_public_url": "TEXT DEFAULT NULL",
        "portal_support_email": "TEXT DEFAULT NULL",
        "portal_allowed_hostname": "TEXT DEFAULT NULL",
        "portal_brand_name": "TEXT DEFAULT NULL",
        "portal_logo_url": "TEXT DEFAULT NULL",
        "portal_terms_url": "TEXT DEFAULT NULL",
        "portal_privacy_url": "TEXT DEFAULT NULL",
        "portal_show_subscription": "INTEGER NOT NULL DEFAULT 1",
        "portal_show_media_access": "INTEGER NOT NULL DEFAULT 1",
        "portal_show_monitoring": "INTEGER NOT NULL DEFAULT 1",
        "portal_show_support": "INTEGER NOT NULL DEFAULT 1",
        "portal_support_content": "TEXT DEFAULT NULL",
        "portal_show_support_email": "INTEGER NOT NULL DEFAULT 1",
        "portal_quick_messages_enabled": "INTEGER NOT NULL DEFAULT 0",
        "portal_show_payment": "INTEGER NOT NULL DEFAULT 0",
        "portal_payment_url": "TEXT DEFAULT NULL",
        "portal_payment_label": "TEXT DEFAULT NULL",
        "portal_local_auth_enabled": "INTEGER NOT NULL DEFAULT 0",
        "portal_plex_auth_enabled": "INTEGER NOT NULL DEFAULT 0",
        "portal_jellyfin_auth_enabled": "INTEGER NOT NULL DEFAULT 0",
        "portal_password_min_length": "INTEGER NOT NULL DEFAULT 8",
        "portal_password_require_upper": "INTEGER NOT NULL DEFAULT 0",
        "portal_password_require_lower": "INTEGER NOT NULL DEFAULT 0",
        "portal_password_require_digit": "INTEGER NOT NULL DEFAULT 0",
        "portal_password_require_symbol": "INTEGER NOT NULL DEFAULT 0",
        "turnstile_enabled": "INTEGER NOT NULL DEFAULT 0",
        "turnstile_site_key": "TEXT DEFAULT NULL",
        "turnstile_secret_key": "TEXT DEFAULT NULL",
        "turnstile_mode": "TEXT NOT NULL DEFAULT 'compact'",
        "turnstile_protect_portal": "INTEGER NOT NULL DEFAULT 0",
        "turnstile_protect_admin": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        ensure_column(cursor, "settings", column, definition)

    if not table_exists(cursor, "portal_accounts"):
        cursor.execute(
            """
            CREATE TABLE portal_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vodum_user_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'invited'
                    CHECK(status IN ('invited','active','suspended','deleted')),
                email_verified_at TIMESTAMP,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(vodum_user_id) REFERENCES vodum_users(id)
                    ON DELETE CASCADE
            )
            """
        )

    if not table_exists(cursor, "portal_roles"):
        cursor.execute(
            """
            CREATE TABLE portal_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_system INTEGER NOT NULL DEFAULT 0
                    CHECK(is_system IN (0, 1)),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    if not table_exists(cursor, "portal_account_roles"):
        cursor.execute(
            """
            CREATE TABLE portal_account_roles (
                portal_account_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(portal_account_id, role_id),
                FOREIGN KEY(portal_account_id) REFERENCES portal_accounts(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(role_id) REFERENCES portal_roles(id)
                    ON DELETE RESTRICT
            )
            """
        )

    if not table_exists(cursor, "portal_auth_identities"):
        cursor.execute(
            """
            CREATE TABLE portal_auth_identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portal_account_id INTEGER NOT NULL,
                provider TEXT NOT NULL
                    CHECK(provider IN ('local','plex','jellyfin')),
                provider_server_id INTEGER,
                provider_subject TEXT NOT NULL,
                normalized_identifier TEXT,
                password_hash TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1)),
                revoked_at TIMESTAMP,
                revoke_reason TEXT,
                verified_at TIMESTAMP,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(portal_account_id) REFERENCES portal_accounts(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(provider_server_id) REFERENCES servers(id)
                    ON DELETE CASCADE,
                CHECK(
                    (provider = 'jellyfin' AND provider_server_id IS NOT NULL)
                    OR (provider != 'jellyfin' AND provider_server_id IS NULL)
                )
            )
            """
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portal_account_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(portal_account_id) REFERENCES portal_accounts(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL CHECK(sender_type IN ('user','admin')),
            body TEXT NOT NULL,
            read_by_admin INTEGER NOT NULL DEFAULT 0,
            read_by_user INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(conversation_id) REFERENCES portal_conversations(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_portal_messages_conversation ON portal_messages(conversation_id,created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_portal_messages_admin_unread ON portal_messages(sender_type,read_by_admin)")

    ensure_column(cursor, "portal_auth_identities", "revoked_at", "TIMESTAMP")
    ensure_column(cursor, "portal_auth_identities", "revoke_reason", "TEXT")

    if not table_exists(cursor, "portal_sessions"):
        cursor.execute(
            """
            CREATE TABLE portal_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portal_account_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                revoked_at TIMESTAMP,
                revoke_reason TEXT,
                FOREIGN KEY(portal_account_id) REFERENCES portal_accounts(id)
                    ON DELETE CASCADE
            )
            """
        )

    if not table_exists(cursor, "portal_account_tokens"):
        cursor.execute(
            """
            CREATE TABLE portal_account_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portal_account_id INTEGER NOT NULL,
                purpose TEXT NOT NULL
                    CHECK(purpose IN ('invitation','password_reset','email_verification')),
                token_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                revoked_at TIMESTAMP,
                FOREIGN KEY(portal_account_id) REFERENCES portal_accounts(id)
                    ON DELETE CASCADE
            )
            """
        )

    if not table_exists(cursor, "portal_login_attempts"):
        cursor.execute(
            """
            CREATE TABLE portal_login_attempts (
                scope TEXT NOT NULL CHECK(scope IN ('ip','email')),
                scope_hash TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                first_failed_at TIMESTAMP,
                last_failed_at TIMESTAMP,
                locked_until TIMESTAMP,
                PRIMARY KEY(scope, scope_hash)
            )
            """
        )

    if not table_exists(cursor, "portal_audit_events"):
        cursor.execute(
            """
            CREATE TABLE portal_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portal_account_id INTEGER,
                event_type TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK(outcome IN ('success','failure','blocked')),
                ip_hash TEXT,
                user_agent_hash TEXT,
                details_json TEXT NOT NULL DEFAULT (json_object()),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(portal_account_id) REFERENCES portal_accounts(id)
                    ON DELETE SET NULL
            )
            """
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portal_request_limits (
            scope_hash TEXT PRIMARY KEY,
            window_started_at TIMESTAMP NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_identity_global_subject
        ON portal_auth_identities(provider, provider_subject)
        WHERE provider_server_id IS NULL
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_identity_server_subject
        ON portal_auth_identities(provider, provider_server_id, provider_subject)
        WHERE provider_server_id IS NOT NULL
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_identity_local_identifier
        ON portal_auth_identities(normalized_identifier)
        WHERE provider = 'local' AND normalized_identifier IS NOT NULL
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_identities_account_active
        ON portal_auth_identities(portal_account_id, is_active)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_sessions_account_active
        ON portal_sessions(portal_account_id, revoked_at, expires_at)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_sessions_expiry
        ON portal_sessions(expires_at)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_tokens_account_purpose
        ON portal_account_tokens(portal_account_id, purpose, used_at, revoked_at)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_tokens_expiry
        ON portal_account_tokens(expires_at)
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_login_attempts_lock "
        "ON portal_login_attempts(locked_until)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_audit_account_created "
        "ON portal_audit_events(portal_account_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_audit_type_created "
        "ON portal_audit_events(event_type, created_at DESC)"
    )
    cursor.executemany(
        """
        INSERT INTO portal_roles(name, description, is_system)
        VALUES (?, ?, 1)
        ON CONFLICT(name) DO UPDATE SET
            description = excluded.description,
            is_system = 1
        """,
        (
            ("admin", "Full VODUM administration access"),
            ("user", "Access to the account owner's portal data"),
        ),
    )
    cursor.execute(
        """
        INSERT OR IGNORE INTO portal_account_roles(portal_account_id,role_id)
        SELECT pa.id,pr.id FROM portal_accounts pa
        JOIN portal_roles pr ON pr.name='user'
        """
    )
    conn.commit()
