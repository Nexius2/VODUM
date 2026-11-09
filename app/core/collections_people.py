"""Memoria's per-configuration selection, shared by movie and series targets."""
import json
from datetime import datetime, timedelta, timezone

from core.collections_repository import group_members, stamp, utcnow


def person_rotation_key(person):
    """Keep the highest web scores; an equal score keeps the earlier detection."""
    detected = person.get('detected_at')
    seniority = -datetime.fromisoformat(detected).timestamp() if detected else float('-inf')
    return (int(person.get('popularity_score') or 0),seniority,
            bool(person.get('manual')),person.get('death_date') or '',person['tmdb_id'])


def members(db, group_id):
    rows = group_members(db,group_id)
    if not rows or any(row['model']!='memoria' for row in rows):
        raise ValueError('collections.not_found')
    return rows


def list_people(db, group_id):
    rows = members(db,group_id)
    minimum = json.loads(rows[0]['config_json']).get('min_popularity',25)
    people = {}
    expired_ids = set()
    for instance in rows:
        if instance['retired']:
            continue
        for row in db.query('''SELECT p.*,o.remote_id,o.state AS object_state FROM collection_people p
                LEFT JOIN collection_objects o ON o.instance_id=p.instance_id AND o.person_key=p.person_key
                WHERE p.instance_id=? ORDER BY p.death_date DESC,p.tmdb_id''',(instance['id'],)):
            if row['expires_at']<=stamp():
                expired_ids.add(row['tmdb_id'])
            if row['expires_at']<=stamp() and not row['remote_id']:
                continue
            data = json.loads(row['data_json'])
            person = people.setdefault(row['tmdb_id'],{'tmdb_id':row['tmdb_id'],'name':row['name'],
                'death_date':row['death_date'],'detected_at':row['detected_at'],'expires_at':row['expires_at'],'libraries':[], 'manual':False,'excluded':False,
                'profile_path':data.get('profile_path'),'popularity_score':int(data['popularity_score']) if data.get('popularity_score') is not None else None})
            if row['remote_id'] and row['object_state']=='synced':
                person['libraries'].append(str(instance['library_id']))
    for choice in db.query('SELECT * FROM collection_person_choices WHERE group_id=?',(group_id,)):
        data = json.loads(choice['data_json'])
        if choice['tmdb_id'] in expired_ids and choice['tmdb_id'] not in people:
            continue
        if choice['expires_at'] and choice['expires_at']<=stamp() and choice['tmdb_id'] not in people or not data.get('name'):
            continue
        person = people.setdefault(choice['tmdb_id'],{'tmdb_id':choice['tmdb_id'],'name':data.get('name',''),
            'death_date':data.get('death_date',''),'detected_at':choice['added_at'],'expires_at':choice['expires_at'],'libraries':[],
            'profile_path':data.get('profile_path'),'popularity_score':int(data['popularity_score']) if data.get('popularity_score') is not None else None})
        person.update(manual=bool(choice['manual']),excluded=bool(choice['excluded']))
        if choice['manual']:
            person['expires_at'] = choice['expires_at']
            person['detected_at'] = choice['added_at']
    ranked = sorted(people.values(),key=lambda person:(not person['excluded'],*person_rotation_key(person)),reverse=True)
    eligible = [person for person in ranked if not person['excluded'] and (not person['expires_at'] or person['expires_at']>stamp())
                and (person['manual'] or (person['popularity_score'] or 0)>=minimum)]
    selected_ids = {person['tmdb_id'] for person in eligible[:json.loads(rows[0]['config_json']).get('max_people',4)]}
    for person in ranked:
        person['status'] = 'excluded' if person['excluded'] else 'cleanup_pending' if person['expires_at'] and person['expires_at']<=stamp() else 'published' if person['libraries'] else 'filtered' if not person['manual'] and (person['popularity_score'] or 0)<minimum else 'waiting' if person['tmdb_id'] in selected_ids else 'not_selected'
    return ranked


def prune_expired_people(db, instance, detection_days):
    """Remove expired profiles only after their owned remote objects are gone.

    Short-lived ID markers prevent a late Wikidata result from starting the
    same expired tribute again. Exclusions keep only an ID and their flag.
    """
    now = stamp()
    with db.transaction() as cur:
        cur.execute('DELETE FROM collection_person_tombstones WHERE instance_id=? AND suppress_until<=?',(instance['id'],now))
        expired = cur.execute('''SELECT p.* FROM collection_people p WHERE p.instance_id=? AND p.expires_at<=?
            AND NOT EXISTS(SELECT 1 FROM collection_objects o WHERE o.instance_id=p.instance_id
                AND o.person_key=p.person_key AND o.remote_id IS NOT NULL AND o.state!='deleted')''',(instance['id'],now)).fetchall()
        for person in expired:
            cur.execute('UPDATE collection_person_choices SET expires_at=COALESCE(expires_at,?) WHERE group_id=? AND tmdb_id=?',
                (person['expires_at'],instance.get('group_id') or instance['id'],person['tmdb_id']))
            try:
                deadline = datetime.fromisoformat(person['death_date']).replace(tzinfo=timezone.utc)+timedelta(days=detection_days+1)
            except ValueError:
                deadline = datetime.fromisoformat(person['expires_at'])+timedelta(days=detection_days)
            if stamp(deadline)>now:
                cur.execute('''INSERT INTO collection_person_tombstones VALUES(?,?,?,?)
                    ON CONFLICT(instance_id,tmdb_id) DO UPDATE SET suppress_until=excluded.suppress_until''',
                    (instance['id'],person['tmdb_id'],person['person_key'],stamp(deadline)))
            cur.execute('DELETE FROM collection_objects WHERE instance_id=? AND person_key=?',(instance['id'],person['person_key']))
            cur.execute('DELETE FROM collection_people WHERE instance_id=? AND person_key=?',(instance['id'],person['person_key']))
        group_id = instance.get('group_id') or instance['id']
        cur.execute('''UPDATE collection_person_choices SET data_json='{}',manual=0 WHERE group_id=? AND expires_at<=?
            AND NOT EXISTS(SELECT 1 FROM collection_people p JOIN collection_instances i ON i.id=p.instance_id
                WHERE i.group_id=collection_person_choices.group_id AND p.tmdb_id=collection_person_choices.tmdb_id)''',(group_id,now))
        cur.execute("DELETE FROM collection_person_choices WHERE group_id=? AND excluded=0 AND manual=0 AND data_json='{}'",(group_id,))


def _locked_members(cursor, group_id):
    rows = cursor.execute('SELECT * FROM collection_instances WHERE group_id=? OR id=?',(group_id,group_id)).fetchall()
    if not rows or any(row['model']!='memoria' for row in rows):
        raise ValueError('collections.not_found')
    if any(row['lease_until'] and row['lease_until']>stamp() or row['requested']=='delete' for row in rows):
        raise ValueError('collections.busy')
    return rows


def _queue(cursor, rows):
    for row in rows:
        if not row['retired']:
            cursor.execute("UPDATE collection_instances SET requested=?,state='queued',updated_at=? WHERE id=?",
                ('sync' if row['enabled'] else 'cleanup',stamp(),row['id']))


def exclude_person(db, group_id, tmdb_id, excluded):
    # Only an existing person in this configuration can be excluded/restored.
    person = next((row for row in list_people(db,group_id) if row['tmdb_id']==tmdb_id),None)
    if not person:
        raise ValueError('collections.person_not_found')
    with db.transaction() as cur:
        rows = _locked_members(cur,group_id)
        cur.execute('''INSERT INTO collection_person_choices(group_id,tmdb_id,excluded,data_json,expires_at)
            VALUES(?,?,?,?,?) ON CONFLICT(group_id,tmdb_id) DO UPDATE SET excluded=excluded.excluded,
            expires_at=COALESCE(collection_person_choices.expires_at,excluded.expires_at)''',
            (group_id,tmdb_id,int(excluded),json.dumps({key:person.get(key) for key in ('name','death_date','profile_path','popularity_score')}),person['expires_at']))
        _queue(cur,rows)


def add_manual_person(db, group_id, person):
    tmdb_id = int(person['tmdb_id'])
    if tmdb_id<=0 or not person.get('name'):
        raise ValueError('collections.person_not_found')
    with db.transaction() as cur:
        rows = _locked_members(cur,group_id)
        config = json.loads(next(row['config_json'] for row in rows if not row['retired']))
        old = cur.execute('SELECT * FROM collection_person_choices WHERE group_id=? AND tmdb_id=?',(group_id,tmdb_id)).fetchone()
        active = old and old['manual'] and not old['excluded'] and old['expires_at'] and old['expires_at']>stamp()
        added = old['added_at'] if active else stamp()
        expires = old['expires_at'] if active else stamp(utcnow()+timedelta(days=config['retention']))
        cur.execute('''INSERT INTO collection_person_choices(group_id,tmdb_id,manual,data_json,added_at,expires_at)
            VALUES(?,?,1,?,?,?) ON CONFLICT(group_id,tmdb_id) DO UPDATE
            SET manual=1,excluded=0,data_json=excluded.data_json,added_at=excluded.added_at,expires_at=excluded.expires_at''',
            (group_id,tmdb_id,json.dumps({key:person.get(key) for key in ('person_key','tmdb_id','name','death_date','profile_path','popularity_score')}),added,expires))
        _queue(cur,rows)
