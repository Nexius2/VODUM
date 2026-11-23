"""Automatic collection intervals and collision-free recurring slots."""
import json
from datetime import datetime, timedelta, timezone
from calendar import monthrange


def next_collection_run(instance, now=None):
    from core.collections_repository import next_occurrence, stamp, utcnow
    config = json.loads(instance['config_json'])
    anchor = config.get('schedule_anchor')
    frequency = config.get('frequency')
    if not instance['enabled']:
        return None
    if not anchor or frequency not in ('daily', 'weekly', 'monthly'):
        return next_occurrence(instance['schedule'], instance['timezone'], now)
    base = datetime.fromisoformat(anchor)
    now = now or utcnow()
    if frequency in ('daily', 'weekly'):
        interval = timedelta(days=1 if frequency == 'daily' else 7)
        return stamp(base + max(1, (now-base)//interval+1)*interval)
    months = max(1, (now.year-base.year)*12 + now.month-base.month)
    while True:
        year, month = divmod(base.year*12 + base.month-1 + months, 12)
        month += 1
        candidate = base.replace(year=year, month=month, day=min(base.day, monthrange(year, month)[1]))
        if candidate > now:
            return stamp(candidate)
        months += 1


def automatic_schedule(cur, config, zone, now, old=None):
    from core.collections_repository import stamp, next_occurrence, collection_timezone
    old_config = json.loads(old['config_json']) if old else {}
    anchor = old_config.get('schedule_anchor')
    if anchor:
        anchor = datetime.fromisoformat(anchor)
    else:
        occupied = []
        for row in cur.execute('SELECT * FROM collection_instances').fetchall():
            row = dict(row)
            if (old and row['id'] == old['id']) or row['retired']:
                continue
            value = json.loads(row['config_json']).get('schedule_anchor') or next_occurrence(row['schedule'], row['timezone'], now)
            if value:
                dt = datetime.fromisoformat(value).astimezone(timezone.utc)
                occupied.append(dt.hour*60 + dt.minute)
        start = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
        for offset in range(1440):
            anchor = start + timedelta(minutes=offset)
            minute = anchor.hour*60 + anchor.minute
            if all(min((minute-other)%1440, (other-minute)%1440) >= 15 for other in occupied):
                break
        else:
            raise ValueError('collections.invalid_schedule')
    config['schedule_anchor'] = stamp(anchor)
    local = anchor.astimezone(collection_timezone(zone))
    frequency = config['frequency']
    day = str(local.day) if frequency == 'monthly' else '*'
    weekday = str((local.weekday()+1)%7) if frequency == 'weekly' else '*'
    return f'{local.minute} {local.hour} {day} * {weekday}'


def migrate_collection_schedules(db):
    from core.collections_repository import utcnow
    # Avoid taking a write lock on every scheduler tick once migration is done.
    candidates = db.query('SELECT config_json FROM collection_instances')
    if not any(json.loads(row['config_json']).get('frequency') in ('daily','weekly','monthly')
               and not json.loads(row['config_json']).get('schedule_anchor') for row in candidates):
        return
    now = utcnow()
    with db.transaction() as cur:
        rows = [dict(row) for row in cur.execute('SELECT * FROM collection_instances ORDER BY created_at,id').fetchall()]
        for row in rows:
            config = json.loads(row['config_json'])
            if row['retired'] or (row['lease_until'] and row['lease_until'] > now.isoformat()) or config.get('schedule_anchor') or config.get('frequency') not in ('daily','weekly','monthly'):
                continue
            schedule = automatic_schedule(cur, config, row['timezone'], now, row)
            updated = {**row, 'schedule': schedule, 'config_json': json.dumps(config)}
            cur.execute('UPDATE collection_instances SET schedule=?,config_json=?,next_run=? WHERE id=?',
                        (schedule, updated['config_json'], next_collection_run(updated, now), row['id']))
