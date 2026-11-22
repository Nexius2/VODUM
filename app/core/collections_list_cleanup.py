"""Explicit cleanup of remote metadata belonging to deleted custom lists."""
import hashlib
import json
import requests
from core.error_reporting import log_handled_failure
from core.collection_lists import read_cursor
from core.collection_inventory import scope_key
from core.collections_repository import stamp, CollectionRunCancelled
from core.collections_media import media_adapter, CollectionOwnershipError


def _targets(cur, key):
    if not cur.execute('SELECT 1 FROM collection_list_deleted WHERE list_id=?', (key,)).fetchone():
        raise ValueError('lists.cleanup_unavailable')
    if cur.execute('SELECT 1 FROM collection_lists WHERE id=?', (key,)).fetchone():
        raise ValueError('lists.cleanup_shared')
    if cur.execute('SELECT 1 FROM collection_list_bindings WHERE list_id=?', (key,)).fetchone():
        raise ValueError('lists.cleanup_shared')
    objects = cur.execute("""SELECT o.*,i.library_id FROM collection_objects o
        JOIN collection_instances i ON i.id=o.instance_id
        WHERE o.person_key IN (?,?) AND o.remote_id IS NOT NULL AND o.state!='deleted'
        ORDER BY o.id""", ('list:movie:'+key, 'list:tv:'+key)).fetchall()
    targets = []
    for obj in objects:
        if cur.execute('SELECT 1 FROM collection_replaced_objects WHERE object_id=? LIMIT 1',(obj['id'],)).fetchone():
            raise ValueError('lists.cleanup_replacements')
        library = dict(cur.execute('SELECT * FROM libraries WHERE id=?', (obj['library_id'],)).fetchone())
        server = dict(cur.execute('SELECT * FROM servers WHERE id=?', (library['server_id'],)).fetchone())
        targets.append({**dict(obj), 'server_name':server['name'], 'library_name':library['name'],
            'server_id':server['id'], 'scope':scope_key(server,library)})
    return targets


def _fingerprint(targets):
    return hashlib.sha256(json.dumps([(row['id'],row['instance_id'],row['remote_id'],row['title'],row['scope']) for row in targets]).encode()).hexdigest()


def cleanup_preview(db, key):
    with read_cursor(db) as cur:
        targets = _targets(cur,key)
    return targets, _fingerprint(targets)


def deleted_list_overview(db):
    with read_cursor(db) as cur:
        return [dict(row) for row in cur.execute("""SELECT d.list_id,d.name,d.deleted_at,
            o.id AS object_id,o.title,o.remote_id,l.name AS library_name,s.name AS server_name,
            COALESCE(q.state,'unrequested') AS cleanup_state,q.error
            FROM collection_list_deleted d JOIN collection_objects o
                ON o.person_key='list:movie:'||d.list_id OR o.person_key='list:tv:'||d.list_id
            JOIN collection_instances i ON i.id=o.instance_id
            JOIN libraries l ON l.id=i.library_id JOIN servers s ON s.id=l.server_id
            LEFT JOIN collection_list_cleanup q ON q.object_id=o.id
            WHERE o.remote_id IS NOT NULL AND o.state!='deleted'
            ORDER BY d.deleted_at DESC,d.list_id,o.id""").fetchall()]


def _unshared(cur,target):
    peer = cur.execute("""SELECT 1 FROM collection_objects o
        JOIN collection_instances i ON i.id=o.instance_id JOIN libraries l ON l.id=i.library_id
        WHERE o.id!=? AND o.remote_id=? AND o.state!='deleted' AND l.server_id=? LIMIT 1""",
        (target['id'],target['remote_id'],target['server_id'])).fetchone()
    if peer:
        raise ValueError('lists.cleanup_shared')


def request_cleanup(db, key, fingerprint, *, confirmed=False):
    if confirmed is not True:
        raise ValueError('lists.delete_confirmation_required')
    with db.transaction() as cur:
        targets = _targets(cur,key)
        if not targets or _fingerprint(targets) != fingerprint:
            raise ValueError('lists.cleanup_changed')
        for target in targets:
            instance = cur.execute('SELECT * FROM collection_instances WHERE id=?', (target['instance_id'],)).fetchone()
            if (instance['model']!='franchises' or instance['requested'] not in (None,'list_cleanup')
                    or instance['lease_until'] and instance['lease_until']>stamp()):
                raise ValueError('collections.busy')
            _unshared(cur,target)
        for target in targets:
            cur.execute("""INSERT INTO collection_list_cleanup(object_id,remote_id,scope)
                VALUES(?,?,?) ON CONFLICT(object_id) DO UPDATE SET remote_id=excluded.remote_id,
                scope=excluded.scope,state='pending',error=NULL,updated_at=CURRENT_TIMESTAMP""",
                (target['id'],target['remote_id'],target['scope']))
            cur.execute("UPDATE collection_instances SET requested='list_cleanup',state='queued',updated_at=? WHERE id=?",
                        (stamp(),target['instance_id']))
            cur.execute('DELETE FROM collection_publication_plans WHERE object_id=?', (target['id'],))
    return len(targets)


def run_list_cleanup(db, instance, *, heartbeat=lambda:None, adapter_factory=None):
    result={'stage':'cleanup','people':[],'warnings':[],'errors':[],'deleted':0}
    adapter = None
    try:
        queue = db.query("""SELECT q.* FROM collection_list_cleanup q JOIN collection_objects o ON o.id=q.object_id
            WHERE o.instance_id=? AND q.state='pending' ORDER BY q.object_id""", (instance['id'],))
        for job in queue:
            heartbeat()
            try:
                with db.transaction() as cur:
                    active=cur.execute("SELECT state FROM collection_list_cleanup WHERE object_id=?",(job['object_id'],)).fetchone()
                    if not active or active[0]!='pending':
                        continue
                    record=cur.execute('SELECT * FROM collection_objects WHERE id=? AND instance_id=?', (job['object_id'],instance['id'])).fetchone()
                    if not record:
                        continue
                    record=dict(record)
                    if record['remote_id'] is None and record['state']=='deleted':
                        cur.execute("UPDATE collection_list_cleanup SET state='done',error=NULL WHERE object_id=?",(job['object_id'],))
                        continue
                    if not record['person_key'].startswith(('list:movie:','list:tv:')):
                        raise ValueError('lists.cleanup_changed')
                    key=record['person_key'].split(':',2)[2]
                    targets=_targets(cur,key)
                    target=next((row for row in targets if row['id']==job['object_id']),None)
                    if not target or target['remote_id']!=job['remote_id'] or target['scope']!=job['scope']:
                        raise ValueError('lists.cleanup_changed')
                    _unshared(cur,target)
                # Adapter deletion verifies the VODUM ownership marker. No
                # network operation is performed while holding a DB transaction.
                if adapter is None:
                    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
                    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
                    if scope_key(server,library)!=job['scope']:
                        raise ValueError('lists.cleanup_changed')
                    adapter=(adapter_factory or media_adapter)(server,library);adapter.heartbeat=heartbeat
                heartbeat()
                adapter.delete(record)
                with db.transaction() as cur:
                    updated=cur.execute("UPDATE collection_objects SET remote_id=NULL,state='deleted' WHERE id=? AND remote_id=?",(record['id'],job['remote_id']))
                    if updated.rowcount!=1:
                        raise ValueError('lists.cleanup_changed')
                    cur.execute("UPDATE collection_list_cleanup SET state='done',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE object_id=?",(record['id'],))
                result['deleted']+=1
            except CollectionRunCancelled:
                raise
            except (ValueError,CollectionOwnershipError) as exc:
                code=str(exc) if str(exc) in ('lists.cleanup_shared','lists.cleanup_changed','lists.cleanup_replacements','collections.ownership_failed','collections.title_collision') else 'collections.ownership_failed'
                db.execute("UPDATE collection_list_cleanup SET state='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE object_id=?",(code,job['object_id']))
                result['errors'].append('collections.ownership_failed')
            except Exception as exc:
                transient=(isinstance(exc,(requests.ConnectionError,requests.Timeout))
                    and not isinstance(exc,requests.exceptions.SSLError)) or getattr(getattr(exc,'response',None),'status_code',None) in (502,503,504)
                if transient:
                    raise
                log_handled_failure('collections.lists.cleanup',level='error')
                db.execute("UPDATE collection_list_cleanup SET state='error',error='lists.cleanup_failed',updated_at=CURRENT_TIMESTAMP WHERE object_id=?",(job['object_id'],))
                result['errors'].append('collections.publication_failed')
        result.update(stage='complete',outcome='failed' if result['errors'] else 'empty')
        return result
    except Exception as exc:
        exc.result=result
        raise
    finally:
        if adapter is not None:
            adapter.close()
