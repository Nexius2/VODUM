"""Independent collection configuration, runs and verified remote ownership."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_server_retries (
 server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
 retry_after TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_discovery_cache (
 cache_key TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_external_ids (
 media_type TEXT NOT NULL, media_id INTEGER NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(media_type,media_id)
);
CREATE TABLE IF NOT EXISTS collection_settings (id INTEGER PRIMARY KEY CHECK(id=1), secret_tmdb TEXT, suppress_empty INTEGER NOT NULL DEFAULT 1);
INSERT OR IGNORE INTO collection_settings(id) VALUES(1);
CREATE TABLE IF NOT EXISTS collection_instances (
 id TEXT PRIMARY KEY, group_id TEXT, retired INTEGER NOT NULL DEFAULT 0, model TEXT NOT NULL, library_id INTEGER NOT NULL REFERENCES libraries(id),
 name TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}', secret_tmdb TEXT,
 enabled INTEGER NOT NULL DEFAULT 0, schedule TEXT, timezone TEXT NOT NULL DEFAULT 'UTC',
 next_run TEXT, requested TEXT, priority_pending INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'idle',
 lease_id TEXT, lease_until TEXT, last_run TEXT, last_error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_collection_due ON collection_instances(enabled,next_run);
CREATE TABLE IF NOT EXISTS collection_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, state TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
 result_json TEXT NOT NULL DEFAULT '{}', error_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_collection_runs_instance ON collection_runs(instance_id,id DESC);
CREATE TABLE IF NOT EXISTS collection_controls (
 instance_id TEXT PRIMARY KEY REFERENCES collection_instances(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL DEFAULT 1, applied_revision INTEGER NOT NULL DEFAULT 0,
 priority_dirty INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending',
 lease_id TEXT, lease_until TEXT, retry_after TEXT, last_error TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS collection_publication_plans (
 object_id TEXT PRIMARY KEY REFERENCES collection_objects(id) ON DELETE CASCADE,
 instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 title TEXT NOT NULL, media_json TEXT NOT NULL, config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_publication_batches (
 instance_id TEXT PRIMARY KEY REFERENCES collection_instances(id) ON DELETE CASCADE,
 signature TEXT NOT NULL, generation TEXT, result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collection_publication_instance ON collection_publication_plans(instance_id);
CREATE TABLE IF NOT EXISTS collection_people (
 instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 person_key TEXT NOT NULL, tmdb_id INTEGER NOT NULL, name TEXT NOT NULL, death_date TEXT NOT NULL,
 detected_at TEXT NOT NULL, expires_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(instance_id,person_key), UNIQUE(instance_id,tmdb_id)
);
CREATE TABLE IF NOT EXISTS collection_objects (
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 person_key TEXT NOT NULL, remote_id TEXT, title TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'reserved', UNIQUE(instance_id,person_key)
);
CREATE TABLE IF NOT EXISTS collection_publication_snapshots (
 object_id TEXT PRIMARY KEY REFERENCES collection_objects(id) ON DELETE CASCADE,
 run_id INTEGER NOT NULL, publication_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_last_counts (
 instance_id TEXT PRIMARY KEY REFERENCES collection_instances(id) ON DELETE CASCADE,
 count_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_run_daily_totals (
 day TEXT PRIMARY KEY, runs INTEGER NOT NULL, failures INTEGER NOT NULL, warnings INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_person_tombstones (
 instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 tmdb_id INTEGER NOT NULL, person_key TEXT NOT NULL, suppress_until TEXT NOT NULL,
 PRIMARY KEY(instance_id,tmdb_id)
);
CREATE TABLE IF NOT EXISTS collection_object_artwork (
 object_id TEXT PRIMARY KEY REFERENCES collection_objects(id) ON DELETE CASCADE,
 remote_id TEXT NOT NULL, digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_replaced_objects (
 object_id TEXT NOT NULL REFERENCES collection_objects(id) ON DELETE CASCADE,
 remote_id TEXT NOT NULL, PRIMARY KEY(object_id,remote_id)
);
CREATE TABLE IF NOT EXISTS collection_unavailable_media (
 library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
 generation TEXT NOT NULL, media_id TEXT NOT NULL,
 PRIMARY KEY(library_id,generation,media_id)
);
CREATE TABLE IF NOT EXISTS collection_person_choices (
 group_id TEXT NOT NULL, tmdb_id INTEGER NOT NULL, excluded INTEGER NOT NULL DEFAULT 0,
 manual INTEGER NOT NULL DEFAULT 0, data_json TEXT NOT NULL DEFAULT '{}',
 added_at TEXT, expires_at TEXT, PRIMARY KEY(group_id,tmdb_id)
);
CREATE TABLE IF NOT EXISTS collection_arr_requests (
 arr_server_id INTEGER NOT NULL REFERENCES servers(id), media_type TEXT NOT NULL, external_id INTEGER NOT NULL,
 instance_id TEXT NOT NULL REFERENCES collection_instances(id), state TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(arr_server_id,media_type,external_id)
);
CREATE TABLE IF NOT EXISTS collection_seasonal_windows (
 instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 event_key TEXT NOT NULL, expires_at TEXT NOT NULL,
 PRIMARY KEY(instance_id,event_key)
);
"""


from core.collections_spotlight_store import SCHEMA as SPOTLIGHT_SCHEMA
SCHEMA += SPOTLIGHT_SCHEMA
from core.collection_inventory import SCHEMA as INVENTORY_SCHEMA
SCHEMA += INVENTORY_SCHEMA


def ensure_collection_schema(conn, cursor):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            cursor.execute(statement)
    settings_columns = {row[1] for row in cursor.execute('PRAGMA table_info(collection_settings)')}
    if 'suppress_empty' not in settings_columns:
        cursor.execute('ALTER TABLE collection_settings ADD COLUMN suppress_empty INTEGER NOT NULL DEFAULT 1')
    columns = {row[1] for row in cursor.execute('PRAGMA table_info(collection_instances)')}
    if 'priority_pending' not in columns:
        cursor.execute('ALTER TABLE collection_instances ADD COLUMN priority_pending INTEGER NOT NULL DEFAULT 0')
    if 'group_id' not in columns:
        cursor.execute('ALTER TABLE collection_instances ADD COLUMN group_id TEXT')
    if 'history_compacted' not in columns:
        cursor.execute('ALTER TABLE collection_instances ADD COLUMN history_compacted INTEGER NOT NULL DEFAULT 0')
    if 'retired' not in columns:
        cursor.execute('ALTER TABLE collection_instances ADD COLUMN retired INTEGER NOT NULL DEFAULT 0')
    cursor.execute('UPDATE collection_instances SET group_id=id WHERE group_id IS NULL')
    repair=cursor.execute("INSERT OR IGNORE INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES('collection-presentation-repair-v1','{}',CURRENT_TIMESTAMP)")
    if repair.rowcount:
        # Repair already published temporary titles/artwork without rebuilding
        # their media or waiting for a weekly/monthly collection refresh.
        cursor.execute("""UPDATE collection_instances SET priority_pending=1,
            state=CASE WHEN requested IS NULL THEN 'queued' ELSE state END,
            requested=COALESCE(requested,'visibility')
            WHERE enabled=1 AND retired=0 AND lease_id IS NULL
              AND EXISTS(SELECT 1 FROM collection_objects o WHERE o.instance_id=collection_instances.id
                  AND o.remote_id IS NOT NULL AND o.state!='deleted')""")
    # Promote an unambiguous legacy key without ever decrypting it here.
    keys = list(cursor.execute("SELECT DISTINCT secret_tmdb FROM collection_instances WHERE secret_tmdb IS NOT NULL AND secret_tmdb!=''"))
    if len(keys)==1:
        cursor.execute('UPDATE collection_settings SET secret_tmdb=COALESCE(secret_tmdb,?) WHERE id=1',(keys[0][0],))
    cursor.execute('UPDATE collection_instances SET secret_tmdb=NULL WHERE EXISTS(SELECT 1 FROM collection_settings WHERE id=1 AND secret_tmdb IS NOT NULL)')
    # Upgrade only legacy midnight defaults; explicit cron schedules stay intact.
    import json
    from core.collections_repository import fixed_collection_name, default_collection_schedule, next_occurrence, streaming_collection_name, recent_collection_name
    instances = list(cursor.execute('SELECT id,model,name,config_json,library_id,schedule,timezone,enabled FROM collection_instances'))
    for row in instances:
        identifier,model,name,raw,library_id,schedule,zone,enabled = row
        config = json.loads(raw or '{}')
        fixed_name = (recent_collection_name if model=='recent_releases' else streaming_collection_name)(config.get('country','FR'),config.get('language','fr')) if model in ('streaming_country','recent_releases') else fixed_collection_name(model,config.get('language','fr'),name)
        cursor.execute('UPDATE collection_instances SET name=? WHERE id=?',(fixed_name,identifier))
        frequency = config.get('frequency','daily')
        if not config.get('schedule_anchor') and frequency in ('daily','weekly') and schedule in ('0 0 * * *','0 0 * * 1'):
            slot = cursor.execute('SELECT COUNT(*) FROM libraries WHERE id<?',(library_id,)).fetchone()[0]
            schedule = default_collection_schedule(model,frequency,slot)
            cursor.execute('UPDATE collection_instances SET schedule=?,next_run=? WHERE id=?',
                (schedule,next_occurrence(schedule,zone) if enabled else None,identifier))
    cursor.execute("""INSERT OR IGNORE INTO collection_controls(instance_id,priority_dirty)
        SELECT id,1 FROM collection_instances WHERE priority_pending=1 OR requested='visibility'""")
    conn.commit()
