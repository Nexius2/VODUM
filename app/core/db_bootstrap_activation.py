"""Additive migration: durable access intent, separate from provider observations."""


def ensure_activation_schema(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activations (
            id INTEGER PRIMARY KEY, vodum_user_id INTEGER NOT NULL UNIQUE
                REFERENCES vodum_users(id) ON DELETE CASCADE,
            token_hash TEXT UNIQUE, email_token TEXT, expires_at INTEGER NOT NULL,
            generation INTEGER NOT NULL DEFAULT 1, mode TEXT NOT NULL,
            expected_email TEXT NOT NULL, plex_subject TEXT,
            plex_token TEXT, plex_token_expires INTEGER,
            completed_at INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activation_servers (
            activation_id INTEGER NOT NULL REFERENCES user_activations(id) ON DELETE CASCADE,
            server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            library_ids TEXT NOT NULL, options_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'queued', error_key TEXT,
            lease_until INTEGER NOT NULL DEFAULT 0, lease_id TEXT,
            PRIMARY KEY(activation_id, server_id)
        )
    """)
    if 'email_token' not in {row[1] for row in cursor.execute('PRAGMA table_info(user_activations)')}:
        cursor.execute('ALTER TABLE user_activations ADD COLUMN email_token TEXT')
