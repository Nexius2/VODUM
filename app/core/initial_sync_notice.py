"""Persistent first-instance date and a bounded dashboard notice."""
from datetime import datetime, timedelta, timezone

from db_manager import isolated_read_operation


def backfill_instance_started_at(cursor, table_exists):
    # Do not restart the clock on upgrades. Use historical seed dates where
    # available; an undated legacy database must not be treated as a new one.
    cursor.execute('SELECT 1 FROM settings WHERE instance_started_at IS NULL LIMIT 1')
    if cursor.fetchone() is None:
        return
    dates = []
    for table in ('subscription_template_seed_state', 'comm_template_seed_state', 'vodum_users'):
        if table_exists(cursor, table):
            cursor.execute(f'PRAGMA table_info({table})')
            column = 'seeded_at' if table.endswith('seed_state') else 'created_at'
            if column in {row[1] for row in cursor.fetchall()}:
                cursor.execute(f'SELECT MIN({column}) FROM {table}')
                value = cursor.fetchone()[0]
                if value:
                    dates.append(str(value))
    cursor.execute('UPDATE settings SET instance_started_at=? WHERE instance_started_at IS NULL',
                   (min(dates) if dates else '1970-01-01 00:00:00',))


@isolated_read_operation
def initial_sync_notice_seconds(db, now=None):
    row = db.query_one('SELECT instance_started_at FROM settings WHERE id=1')
    if not row or not row['instance_started_at']:
        return 0
    try:
        started = datetime.fromisoformat(str(row['instance_started_at']).replace('Z', '+00:00'))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0
    now = now or datetime.now(timezone.utc)
    if not started <= now < started + timedelta(hours=24):
        return 0
    return (started + timedelta(hours=24) - now).total_seconds()
