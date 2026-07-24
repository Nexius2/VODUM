from __future__ import annotations


def ensure_stream_enforcement_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
):
    # -------------------------------------------------
    # 0.2 Stream policies tables (NEW)
    # -------------------------------------------------
    if not table_exists(cursor, "stream_policies"):
        print("Creating table: stream_policies")
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
        print("Creating table: stream_enforcement_state")
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
        print("Creating table: stream_enforcements")
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

    # ? IMPORTANT : migrations m?me si la table existe d?j?
    ensure_column(cursor, "stream_enforcements", "account_username", "TEXT")
    ensure_column(cursor, "stream_enforcements", "ips_json", "TEXT")
    ensure_column(cursor, "stream_enforcements", "details_json", "TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_enforcements_vodum_user_created ON stream_enforcements(vodum_user_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_enforcements_external_user_created ON stream_enforcements(external_user_id, created_at)")
