from __future__ import annotations

import uuid


def ensure_admin_auth_schema(conn, cursor, *, table_exists):
    """Create the provider-neutral admin authentication identity store.

    Local credentials deliberately remain in ``settings`` for now.  This
    schema records which identities may authenticate the singleton VODUM admin
    without coupling them to media users, servers, or provider sync tokens.
    """
    if not table_exists(cursor, "admin_accounts"):
        cursor.execute(
            """
            CREATE TABLE admin_accounts (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                plex_client_identifier TEXT UNIQUE,
                plex_require_vodum_totp INTEGER NOT NULL DEFAULT 0
                    CHECK(plex_require_vodum_totp IN (0, 1)),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    cursor.execute("PRAGMA table_info(admin_accounts)")
    account_columns = {row[1] for row in cursor.fetchall()}
    if "plex_client_identifier" not in account_columns:
        cursor.execute(
            "ALTER TABLE admin_accounts ADD COLUMN plex_client_identifier TEXT"
        )
    if "plex_require_vodum_totp" not in account_columns:
        cursor.execute(
            """
            ALTER TABLE admin_accounts
            ADD COLUMN plex_require_vodum_totp INTEGER NOT NULL DEFAULT 0
                CHECK(plex_require_vodum_totp IN (0, 1))
            """
        )

    cursor.execute("INSERT OR IGNORE INTO admin_accounts(id) VALUES (1)")
    cursor.execute(
        """
        UPDATE admin_accounts
        SET plex_client_identifier = ?
        WHERE id = 1 AND (
            plex_client_identifier IS NULL OR TRIM(plex_client_identifier) = ''
        )
        """,
        (str(uuid.uuid4()),),
    )

    if not table_exists(cursor, "admin_auth_identities"):
        cursor.execute(
            """
            CREATE TABLE admin_auth_identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_account_id INTEGER NOT NULL DEFAULT 1,
                provider TEXT NOT NULL,
                provider_subject TEXT NOT NULL,
                display_name TEXT,
                display_email TEXT,
                discovery_token_enc TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1)),
                linked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(admin_account_id) REFERENCES admin_accounts(id)
                    ON DELETE CASCADE,
                UNIQUE(admin_account_id, provider),
                UNIQUE(provider, provider_subject)
            )
            """
        )

    cursor.execute("PRAGMA table_info(admin_auth_identities)")
    identity_columns = {row[1] for row in cursor.fetchall()}
    if "discovery_token_enc" not in identity_columns:
        cursor.execute(
            "ALTER TABLE admin_auth_identities ADD COLUMN discovery_token_enc TEXT"
        )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_auth_identities_active_provider
        ON admin_auth_identities(is_active, provider)
        """
    )

    if not table_exists(cursor, "plex_discovery_candidates"):
        cursor.execute(
            """
            CREATE TABLE plex_discovery_candidates (
                id TEXT PRIMARY KEY,
                discovery_id TEXT NOT NULL,
                session_fingerprint TEXT NOT NULL,
                provider_subject TEXT NOT NULL,
                machine_identifier TEXT NOT NULL,
                name TEXT NOT NULL,
                is_owned INTEGER NOT NULL DEFAULT 0,
                presence INTEGER NOT NULL DEFAULT 0,
                connections_json TEXT NOT NULL DEFAULT '[]',
                access_token_enc TEXT,
                expires_at INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(discovery_id, machine_identifier)
            )
            """
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plex_discovery_expiry
        ON plex_discovery_candidates(expires_at)
        """
    )
    cursor.execute(
        "DELETE FROM plex_discovery_candidates WHERE expires_at < CAST(strftime('%s','now') AS INTEGER)"
    )

    # Existing installations retain settings as the source of local login.
    # The identity row is metadata only and therefore changes no auth behavior.
    if table_exists(cursor, "settings"):
        cursor.execute("PRAGMA table_info(settings)")
        settings_columns = {row[1] for row in cursor.fetchall()}
        if {"admin_email", "admin_password_hash"}.issubset(settings_columns):
            cursor.execute(
                "SELECT admin_email, admin_password_hash FROM settings WHERE id = 1"
            )
            row = cursor.fetchone()
            admin_email = (row[0] or "").strip() if row else ""
            password_hash = (row[1] or "").strip() if row else ""
            if admin_email and password_hash:
                cursor.execute(
                    """
                    INSERT INTO admin_auth_identities(
                        admin_account_id, provider, provider_subject,
                        display_email, is_active
                    ) VALUES (1, 'local', ?, ?, 1)
                    ON CONFLICT(admin_account_id, provider) DO UPDATE SET
                        provider_subject = excluded.provider_subject,
                        display_email = excluded.display_email,
                        is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (admin_email.casefold(), admin_email),
                )

    conn.commit()
