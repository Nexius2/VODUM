"""Durable, independent lane for small presentation commands."""
import json
import threading
import time
import uuid
from datetime import timedelta
from core.collections_repository import CollectionRunCancelled, stamp, utcnow
from core.collections_visibility import run_visibility
from core.tasks.worker_lease import WorkerLease

_worker=WorkerLease()


def queue_control(cursor, instance_id, *, priority=False):
    cursor.execute("""INSERT INTO collection_controls(instance_id,priority_dirty) VALUES(?,?)
        ON CONFLICT(instance_id) DO UPDATE SET revision=revision+1,state='pending',
        priority_dirty=MAX(priority_dirty,excluded.priority_dirty),retry_after=NULL,
        last_error=NULL,updated_at=CURRENT_TIMESTAMP""",(instance_id,int(priority)))


def process_controls(db, *, runner=run_visibility):
    count=0
    while True:
        now=stamp();lease=str(uuid.uuid4())
        with db.transaction() as cursor:
            job=cursor.execute("""SELECT c.* FROM collection_controls c JOIN collection_instances i ON i.id=c.instance_id
                WHERE c.revision>c.applied_revision AND i.retired=0 AND i.requested IS NOT 'delete'
                AND (c.retry_after IS NULL OR c.retry_after<=?)
                AND (c.lease_until IS NULL OR c.lease_until<=?)
                ORDER BY c.updated_at,c.instance_id LIMIT 1""",(now,now)).fetchone()
            if job is None:return count
            job=dict(job)
            cursor.execute("UPDATE collection_controls SET state='running',lease_id=?,lease_until=? WHERE instance_id=?",
                (lease,stamp(utcnow()+timedelta(minutes=2)),job['instance_id']))
            instance=dict(cursor.execute('SELECT * FROM collection_instances WHERE id=?',(job['instance_id'],)).fetchone())
        next_renewal=0
        def heartbeat():
            nonlocal next_renewal
            row=db.query_one('SELECT revision,lease_id FROM collection_controls WHERE instance_id=?',(job['instance_id'],))
            if not row or row['lease_id']!=lease or row['revision']!=job['revision']:
                raise CollectionRunCancelled('Presentation command superseded')
            if time.monotonic()>=next_renewal:
                db.execute('UPDATE collection_controls SET lease_until=? WHERE instance_id=? AND lease_id=?',
                    (stamp(utcnow()+timedelta(minutes=2)),job['instance_id'],lease))
                next_renewal=time.monotonic()+20
        heartbeat.priority=True
        heartbeat.metrics={}
        failed=False;superseded=False;unsupported=False
        try:
            result=runner(db,instance,heartbeat=heartbeat,reorder=bool(job['priority_dirty']))
            unsupported='collections.jellyfin_home_not_supported' in result.get('warnings',[])
            failed=bool(result.get('errors') or result.get('warnings') or result.get('diagnostics',{}).get('visibility_failures'))
        except CollectionRunCancelled:
            superseded=True
        except Exception:
            from core.error_reporting import log_handled_failure
            log_handled_failure('collections.control',level='error')
            failed=True
        with db.transaction() as cursor:
            cursor.execute("""UPDATE collection_controls SET lease_id=NULL,lease_until=NULL,
                applied_revision=CASE WHEN revision=? AND ?=0 AND ?=0 THEN ? ELSE applied_revision END,
                priority_dirty=CASE WHEN revision=? AND ?=0 AND ?=0 THEN 0 ELSE priority_dirty END,
                state=CASE WHEN revision!=? OR ?=1 THEN 'pending' WHEN ?=1 THEN 'error' ELSE 'applied' END,
                retry_after=CASE WHEN revision=? AND ?=1 THEN ? ELSE NULL END,
                last_error=CASE WHEN revision=? AND ?=1 THEN 'collections.priority_not_applied' ELSE NULL END
                WHERE instance_id=? AND lease_id=?""",
                (job['revision'],int(failed),int(superseded),job['revision'],
                 job['revision'],int(failed),int(superseded),job['revision'],int(superseded),int(failed),
                 job['revision'],int(failed),stamp(utcnow()+timedelta(seconds=86400 if unsupported else 30)),
                 job['revision'],int(failed),job['instance_id'],lease))
            if not failed and not superseded:
                cursor.execute("""UPDATE collection_instances SET priority_pending=0,
                    requested=CASE WHEN requested='visibility' THEN NULL ELSE requested END,
                    state=CASE WHEN requested='visibility' AND lease_id IS NULL THEN 'idle' ELSE state END
                    WHERE id=? AND EXISTS(SELECT 1 FROM collection_controls WHERE instance_id=? AND state='applied')""",
                    (job['instance_id'],job['instance_id']))
        count+=1


def start_controls(db):
    # The DB lease also guards multiple application processes. The thread flag
    # avoids producing an extra waiting thread on every browser save/tick.
    if not db.query_one("""SELECT c.instance_id FROM collection_controls c JOIN collection_instances i ON i.id=c.instance_id
        WHERE c.revision>c.applied_revision AND i.retired=0 AND i.requested IS NOT 'delete'
        AND (c.retry_after IS NULL OR c.retry_after<=?) AND (c.lease_until IS NULL OR c.lease_until<=?) LIMIT 1""",(stamp(),stamp())):
        return False
    if not _worker.claim():return False
    def work():
        try:process_controls(db)
        except Exception:
            from core.error_reporting import log_handled_failure
            log_handled_failure('collections.control.worker',level='error')
        finally:
            _worker.release()
    try:threading.Thread(target=work,name='vodum-collection-controls',daemon=True).start()
    except Exception:
        _worker.release();raise
    return True
