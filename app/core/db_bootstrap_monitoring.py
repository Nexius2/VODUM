from __future__ import annotations


def ensure_import_monitoring_schema(
    conn,
    cursor,
    *,
    table_exists,
    ensure_column,
):
    # -------------------------------------------------
    # 0.3 Tautulli import jobs
    # -------------------------------------------------
    if not table_exists(cursor, "tautulli_import_jobs"):
        print("Creating table: tautulli_import_jobs")
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

    # ? IMPORTANT : ces migrations doivent ?tre ex?cut?es m?me si la table existe d?j?


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
        print("Creating table: monitoring_snapshots")
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
        print("Creating table: monitoring_server_resources")
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
