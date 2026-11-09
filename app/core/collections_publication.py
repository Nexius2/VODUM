"""Persist publication inputs so automatic continuations never rediscover media."""
import hashlib
import json
from datetime import timedelta
from core.collection_inventory import CachedCollectionMedia, serializable_media, scope_key
from core.collections_repository import stamp,utcnow

PENDING={'collections.membership_pending','collections.order_pending'}


def signature(instance):
    config=json.loads(instance['config_json'])
    for key in ('visibility','priority','mode','arr_enabled','arr_server'):config.pop(key,None)
    return hashlib.sha256(json.dumps([instance['model'],instance['library_id'],config],sort_keys=True).encode()).hexdigest()


def record_plan(db,record,title,matches,config):
    if not record.get('instance_id') or not record.get('id'):return
    db.execute("""INSERT INTO collection_publication_plans VALUES(?,?,?,?,?)
        ON CONFLICT(object_id) DO UPDATE SET title=excluded.title,media_json=excluded.media_json,config_json=excluded.config_json""",
        (record['id'],record['instance_id'],title,json.dumps([serializable_media(row) for row in matches]),json.dumps(config)))


def finish_plan(db,object_id,warnings):
    if not PENDING.intersection(warnings or []):
        db.execute('DELETE FROM collection_publication_plans WHERE object_id=?',(object_id,))


def prepare_batch(db,instance,result):
    # Unfinished acquisition and discovery still need their own engine.
    config=json.loads(instance['config_json']);diagnostics=result.get('diagnostics',{})
    arr_complete=(result.get('stage')=='complete' and not diagnostics.get('catalog_acquisition_pending')
        and not any(warning.startswith(('collections.arr_pending','collections.arr_blocked','collections.arr_server_offline','collections.arr_media_failed'))
            for warning in result.get('warnings',[])))
    if config.get('arr_enabled') and not arr_complete:return
    if result.get('errors') or any(
        diagnostics.get(key) for key in ('availability_deferred','origin_deferred')):return
    if not db.query_one('SELECT object_id FROM collection_publication_plans WHERE instance_id=? LIMIT 1',(instance['id'],)):return
    inventory=db.query_one('SELECT generation FROM collection_inventory WHERE library_id=?',(instance['library_id'],))
    result.setdefault('diagnostics',{})['publication_arr_complete']=bool(config.get('arr_enabled') and arr_complete)
    result['diagnostics']['publication_arr_server']=config.get('arr_server')
    db.execute("""INSERT OR REPLACE INTO collection_publication_batches VALUES(?,?,?,?)""",
        (instance['id'],signature(instance),inventory['generation'] if inventory else None,json.dumps(result)))


def resume_batch(db,instance,*,heartbeat):
    batch=db.query_one('SELECT * FROM collection_publication_batches WHERE instance_id=?',(instance['id'],))
    if not batch:return None
    result=json.loads(batch['result_json'])
    current_config=json.loads(instance['config_json'])
    acquisition_valid=(not current_config.get('arr_enabled') or result.get('diagnostics',{}).get('publication_arr_complete')
        and result.get('diagnostics',{}).get('publication_arr_server')==current_config.get('arr_server'))
    inventory=db.query_one('SELECT * FROM collection_inventory WHERE library_id=?',(instance['library_id'],))
    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    valid=(inventory and inventory['generation'] and not inventory['last_error']
        and inventory['completed_at']
        and inventory['completed_at']>=stamp(utcnow()-timedelta(hours=36))
        and inventory['scope']==scope_key(server,library)
        and batch['signature']==signature(instance) and batch['generation']==inventory['generation']
        and acquisition_valid
        and (not instance['next_run'] or instance['next_run']>stamp()))
    if not valid:
        discard_batch(db,instance['id']);return None
    adapter=CachedCollectionMedia(db,server,library);adapter.heartbeat=heartbeat
    result['warnings']=[warning for warning in result.get('warnings',[]) if warning not in PENDING]
    result['stage']='publish';result.setdefault('diagnostics',{})['publication_resumed']=True
    plans=db.query("""SELECT p.*,o.remote_id,o.person_key,o.state FROM collection_publication_plans p
        JOIN collection_objects o ON o.id=p.object_id WHERE p.instance_id=? ORDER BY p.object_id""",(instance['id'],))
    try:
        for plan in plans:
            heartbeat()
            config=json.loads(plan['config_json'])
            matches=adapter.restore_items(json.loads(plan['media_json']))
            record={'id':plan['object_id'],'instance_id':instance['id'],'remote_id':plan['remote_id'],
                'person_key':plan['person_key'],'state':plan['state'],'title':plan['title']}
            def created(remote_id):
                db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,record['id']))
            result['warnings'].extend(adapter.sync(record,plan['title'],matches,config,created) or [])
            db.execute("UPDATE collection_objects SET state='synced' WHERE id=?",(record['id'],))
        result['warnings']=list(dict.fromkeys(result['warnings']))
        result['stage']='complete'
        if db.query_one('SELECT object_id FROM collection_publication_plans WHERE instance_id=? LIMIT 1',(instance['id'],)):
            db.execute('UPDATE collection_publication_batches SET result_json=? WHERE instance_id=?',(json.dumps(result),instance['id']))
        else:discard_batch(db,instance['id'])
        return result
    except Exception as exc:
        exc.result=result
        raise
    finally:adapter.close()


def discard_batch(db,instance_id):
    with db.transaction() as cursor:
        cursor.execute('DELETE FROM collection_publication_batches WHERE instance_id=?',(instance_id,))
        cursor.execute('DELETE FROM collection_publication_plans WHERE instance_id=?',(instance_id,))
