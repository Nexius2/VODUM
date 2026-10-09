"""Track aggregate source changes, including imports and cascading deletions."""


def ensure_daily_refresh_schema(cursor):
    columns = {row[1] for row in cursor.execute('PRAGMA table_info(monitoring_daily_stats)')}
    for column in ('source_revision', 'identity_revision'):
        if column not in columns:
            cursor.execute(f'ALTER TABLE monitoring_daily_stats ADD COLUMN {column} INTEGER NOT NULL DEFAULT -1')
    cursor.execute('''CREATE TABLE IF NOT EXISTS monitoring_daily_revisions (
        day TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS monitoring_identity_revision (
        id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL DEFAULT 0)''')
    cursor.execute('INSERT OR IGNORE INTO monitoring_identity_revision(id, revision) VALUES(1, 0)')

    def mark_day(record):
        return f'''INSERT INTO monitoring_daily_revisions(day, revision)
            SELECT substr({record}.stopped_at, 1, 10), 1
            WHERE {record}.stopped_at IS NOT NULL
            ON CONFLICT(day) DO UPDATE SET revision = revision + 1;'''

    updates = ('id', 'server_id', 'media_key', 'media_type', 'title', 'grandparent_title',
               'external_user_id', 'media_user_id', 'watch_ms', 'duration_ms', 'started_at', 'stopped_at')
    changed = ' OR '.join(f'OLD.{column} IS NOT NEW.{column}' for column in updates)
    for event, records, condition in (
        ('INSERT', ('NEW',), ''), ('DELETE', ('OLD',), ''),
        ('UPDATE', ('OLD', 'NEW'), ' WHEN ' + changed),
    ):
        body = '\n'.join(mark_day(record) for record in records)
        cursor.execute(f'''CREATE TRIGGER IF NOT EXISTS monitoring_daily_history_{event.lower()}
            AFTER {event} ON media_session_history{condition} BEGIN {body} END''')

    for table, fields in (('media_users', ('id', 'vodum_user_id', 'username')),
                          ('vodum_users', ('id', 'username'))):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            condition = ''
            if event == 'UPDATE':
                condition = ' WHEN ' + ' OR '.join(f'OLD.{field} IS NOT NEW.{field}' for field in fields)
            cursor.execute(f'''CREATE TRIGGER IF NOT EXISTS monitoring_identity_{table}_{event.lower()}
                AFTER {event} ON {table}{condition} BEGIN
                UPDATE monitoring_identity_revision SET revision = revision + 1 WHERE id = 1;
                END''')
