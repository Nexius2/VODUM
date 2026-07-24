from __future__ import annotations


def ensure_migration_foundation_schema(conn, cursor):
    # -------------------------------------------------
    # 0.6 User migration foundations
    # -------------------------------------------------
    cursor.executescript("""
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
    """)
    conn.commit()
