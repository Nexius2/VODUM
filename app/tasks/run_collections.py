from core.collections_history import compact_legacy_collection_history, store_finished_run
from core.collections_hidden_gems import run_hidden_gems
from core.collections_platforms import run_platforms
from core.collections_continents import run_continents
from core.collections_franchises import run_franchises
from core.collections_awards import run_awards
from core.collections_family import run_family
from core.collections_top_country import run_top_country
from core.collections_visibility import run_visibility
from core.collections_tmdb import run_tmdb
from core.collections_kids import run_kids
from core.collections_recently_added import run_recently_added
"""Daily sweep and per-instance requests share VODUM's normal task worker."""
import json
import uuid
import time
import requests
from datetime import timedelta

from core.collections_repository import due_sql, next_occurrence, next_collection_run, stamp, utcnow, global_timezone, CollectionRunCancelled, recover_stale_collection_runs
from core.collections_memoria import run_memoria
from core.collections_spotlight import run_spotlight
from core.collections_imdb import run_imdb
from core.collections_recent_releases import run_recent_releases
from core.collections_seasonal import run_seasonal
from core.collections_streaming import run_streaming_country, run_streaming_worldwide
from core.collections_media import CollectionOwnershipError
from core.error_reporting import log_handled_failure
from tasks_engine import task_logs
from logging_utils import is_debug_mode_enabled

# Cooperative deadline checked before external calls; individual HTTP timeouts
# still bound a request already in flight. Keep other configurations runnable.
MAX_INSTANCE_SECONDS = 15 * 60
# Franchises fans out to many independently published collections. Its batch
# budget must not be the same as the budget for one chart/collection.
MAX_FRANCHISE_SECONDS = 60 * 60


class CollectionRunTimedOut(CollectionRunCancelled):
    pass


ENGINES = {'hidden_gems':run_hidden_gems,'platforms':run_platforms,'continents':run_continents,'franchises':run_franchises,'top_country':run_top_country,'awards':run_awards,'family':run_family,'tmdb':run_tmdb,'kids':run_kids,'recently_added':run_recently_added,'imdb':run_imdb,'memoria':run_memoria,'spotlight':run_spotlight,'streaming_country':run_streaming_country,'streaming_worldwide':run_streaming_worldwide,'recent_releases':run_recent_releases,'seasonal':run_seasonal}


# Only known public error keys may be shown in collection rows.
VISIBLE_ERRORS={
    'collections.franchises_source_failed','collections.platforms_source_failed',
    'collections.awards_source_unavailable','collections.awards_source_invalid',
    'collections.run_timed_out','collections.inventory_required','collections.inventory_unavailable',
    'collections.inventory_dates_required','collections.inventory_invalid','collections.inventory_connection_failed',
    'collections.inventory_auth_failed','collections.inventory_tls_failed','collections.inventory_address_invalid',
    'collections.inventory_storage_failed','collections.ownership_failed','collections.title_collision',
    'collections.jellyfin_response_invalid','collections.jellyfin_item_unavailable','collections.plex_order_rejected','collections.publication_failed','collections.plex_title_rejected','collections.family_audio_unknown','collections.streaming_incomplete',
    'collections.streaming_empty','collections.streaming_source_invalid','collections.streaming_unavailable',
    'collections.imdb_source_unavailable','collections.imdb_source_invalid','collections.tmdb_key_required',
}


def visible_run_error(result, error_type=None):
    if error_type=='CollectionRunTimedOut':return 'collections.run_timed_out'
    return next((code for code in result.get('errors',[]) if isinstance(code,str) and code in VISIBLE_ERRORS),
                'collections.execution_failed')


def run(task_id, db):
    from core.server_cooldown import should_skip_unreachable_server
    recover_stale_collection_runs(db)
    compact_legacy_collection_history(db)
    now = stamp()
    candidates = db.query(due_sql(),(now,now,now))
    completed = failed = 0
    execution_id = str(uuid.uuid4())
    failed_instances = []
    for candidate in candidates:
        server = db.query_one('''SELECT s.* FROM servers s
            JOIN libraries l ON l.server_id=s.id WHERE l.id=?''',(candidate['library_id'],))
        # Leave queued actions and their schedule untouched until health checks
        # confirm recovery; do not acquire a lease or record a failed run.
        if should_skip_unreachable_server(server):
            continue
        retry = db.query_one('SELECT retry_after FROM collection_server_retries WHERE server_id=?',(server['id'],)) if server else None
        if retry and retry['retry_after']>stamp():
            continue
        lease = str(uuid.uuid4())
        now = utcnow()
        with db.transaction() as cur:
            # A queued collection may have been edited or stopped since the
            # task took its initial snapshot of due configurations.
            current = stamp(now)
            if not cur.execute('SELECT id FROM ('+due_sql()+') WHERE id=?',(current,current,current,candidate['id'])).fetchone():
                continue
            row = cur.execute('SELECT * FROM collection_instances WHERE id=?',(candidate['id'],)).fetchone()
            if not row or row['lease_until'] and row['lease_until'] > stamp(now):
                continue
            instance = dict(row)
            kind = instance['requested'] or ('sync' if instance['enabled'] and instance['next_run'] and instance['next_run']<=stamp(now) else 'expire' if instance['enabled'] else 'cleanup')
            cur.execute("UPDATE collection_instances SET state='running',lease_id=?,lease_until=?,requested=NULL WHERE id=?",
                (lease,stamp(now+timedelta(minutes=10)),instance['id']))
            cur.execute("INSERT INTO collection_runs(instance_id,kind,state,started_at) VALUES(?,?,'running',?)",(instance['id'],kind,stamp(now)))
            run_id = cur.lastrowid
            # A prior worker terminated without finishing. Preserve its history.
            cur.execute("UPDATE collection_runs SET state='interrupted',finished_at=? WHERE instance_id=? AND id!=? AND state='running'",
                (stamp(now),instance['id'],run_id))
        deadline = time.monotonic() + (MAX_FRANCHISE_SECONDS if instance['model']=='franchises' else MAX_INSTANCE_SECONDS)
        partial_result = {}
        next_checkpoint = 0
        next_lease_refresh = 0
        def checkpoint(progress):
            nonlocal partial_result
            partial_result = progress
            progress['execution_id'] = execution_id
            progress['elapsed_seconds'] = round((utcnow()-now).total_seconds(),1)
            db.execute("UPDATE collection_runs SET result_json=? WHERE id=? AND state='running'",
                (json.dumps({key:value for key,value in progress.items() if key!='people'}),run_id))
        def heartbeat():
            nonlocal next_checkpoint, next_lease_refresh
            tick = time.monotonic()
            if tick >= deadline:
                raise CollectionRunTimedOut()
            control = db.query_one('SELECT requested,lease_id FROM collection_instances WHERE id=?',(instance['id'],))
            if not control or control['lease_id']!=lease:
                raise CollectionRunCancelled('Collection lease was lost')
            if control['requested']=='cancel':
                raise CollectionRunCancelled('Collection stop requested')
            # Local inventory loops call this tens of thousands of times.
            # Check cancellation every time, but avoid committing the same
            # ten-minute lease on every item and every rate-limit wait tick.
            if tick>=next_lease_refresh:
                updated = db.execute('UPDATE collection_instances SET lease_until=? WHERE id=? AND lease_id=?',
                    (stamp(utcnow()+timedelta(minutes=10)),instance['id'],lease))
                if updated.rowcount != 1:
                    raise CollectionRunCancelled('Collection lease was lost')
                next_lease_refresh=tick+30
            if partial_result and tick>=next_checkpoint:
                checkpoint(partial_result)
                next_checkpoint = tick+5
        heartbeat.report = checkpoint
        heartbeat.metrics = {}
        heartbeat.bootstrap_inventory = True
        task_logs(task_id,'info',f"Collection started instance={instance['id']} model={instance['model']} library={instance['library_id']} kind={kind}")
        result, error_type, state = {}, None, 'success'
        retry_after = None
        try:
            engine = ENGINES.get(instance['model'])
            if kind=='visibility':
                result=run_visibility(db,instance,heartbeat=heartbeat)
            elif engine is None and kind in ('cleanup','delete') and not db.query_one('SELECT id FROM collection_objects WHERE instance_id=?',(instance['id'],)):
                result = {}
            elif engine is None:
                raise ValueError('collections.engine_unavailable')
            else:
                from core.collections_publication import resume_batch,prepare_batch,discard_batch
                presentation=None
                if kind=='sync' and instance.get('priority_pending') and not db.query_one(
                        'SELECT instance_id FROM collection_controls WHERE instance_id=?',(instance['id'],)):
                    # An already queued refresh must not defer a priority edit
                    # until after slow discovery, inventory or membership work.
                    presentation=run_visibility(db,instance,heartbeat=heartbeat)
                    if not presentation.get('errors') and 'collections.priority_not_applied' not in presentation.get('warnings',[]):
                        db.execute('UPDATE collection_instances SET priority_pending=0 WHERE id=?',(instance['id'],))
                result=resume_batch(db,instance,heartbeat=heartbeat) if kind=='sync' else None
                if result is None:
                    if kind!='preview':discard_batch(db,instance['id'])
                    result = engine(db,instance,kind=kind,heartbeat=heartbeat)
                    if kind=='sync':prepare_batch(db,instance,result)
                if kind=='sync' and db.query_one(
                        "SELECT id FROM collection_objects WHERE instance_id=? AND remote_id IS NOT NULL AND state!='deleted' LIMIT 1",
                        (instance['id'],)):
                    # Reconcile existing Plex positions too: an earlier hub
                    # promotion or manual move may have left the order stale.
                    from core.collections_control import queue_control
                    with db.transaction() as cursor:
                        queue_control(cursor,instance['id'],priority=True)
                if presentation:
                    result.setdefault('warnings',[]).extend(presentation.get('warnings',[]))
                    result.setdefault('diagnostics',{})['visibility_failures']=presentation.get('diagnostics',{}).get('visibility_failures',[])
            if kind=='visibility' and not result.get('errors') and 'collections.priority_not_applied' not in result.get('warnings',[]):
                db.execute('UPDATE collection_instances SET priority_pending=0 WHERE id=?',(instance['id'],))
            if result.get('errors'):
                state = 'error'
            elif result.get('warnings'):
                state = 'warning'
        except CollectionRunTimedOut as exc:
            error_type, state = 'CollectionRunTimedOut', 'error'
            result = getattr(exc,'result',partial_result)
            result.setdefault('errors',[]).append('collections.run_timed_out')
        except CollectionRunCancelled as exc:
            state = 'cancelled'
            result = getattr(exc,'result',partial_result)
            result.setdefault('warnings',[]).append('collections.run_cancelled')
        except Exception as exc:
            transient = (isinstance(exc,(requests.exceptions.ConnectionError,requests.exceptions.Timeout))
                and not isinstance(exc,requests.exceptions.SSLError)) or (
                getattr(getattr(exc,'response',None),'status_code',None) in (502,503,504))
            error_type, state = type(exc).__name__, 'warning' if transient else 'error'
            if transient:
                retry_after=stamp(utcnow()+timedelta(minutes=10))
                db.execute('INSERT OR REPLACE INTO collection_server_retries(server_id,retry_after) VALUES(?,?)',
                    (server['id'],retry_after))
                task_logs(task_id,'warning',
                    f"Connexion au serveur {server['name']} (id={server['id']}) interrompue, redémarrage possible. "
                    f"Collection {instance['name']} : nouvelle tentative dans 10 minutes, après vérification de sa disponibilité.",
                    details={'server_id':server['id'],'instance_id':instance['id'],'retry_after':retry_after})
            else:
                log_handled_failure('collections.run_instance',level='error',run_id=run_id,
                    context={'collection_name':instance['name'],'instance_id':instance['id'],'server_name':server['name'] if server else ''},library_id=instance['library_id'])
            # Exception text from external services may contain credentials.
            code = str(exc) if isinstance(exc,ValueError) and str(exc).startswith('collections.') else 'collections.execution_failed'
            if isinstance(exc,RuntimeError) and str(exc)=='collections.publication_failed':
                code = 'collections.publication_failed'
            if isinstance(exc,CollectionOwnershipError) and str(exc) in {
                    'collections.ownership_failed','collections.title_collision'}:
                code = str(exc)
            result = getattr(exc,'result',partial_result)
            if transient:
                result.setdefault('warnings',[]).append('collections.server_retry_pending')
                result['retry_after']=retry_after
            else:
                result.setdefault('errors',[]).append(code)
            result['error_type'] = error_type
            status=getattr(getattr(exc,'response',None),'status_code',None)
            if isinstance(status,int):result.setdefault('diagnostics',{})['http_failure']={'status':status,'operation':getattr(exc,'collection_operation','collection_request')}
        result['execution_id'] = execution_id
        result.setdefault('diagnostics',{})['transport']=heartbeat.metrics
        result['elapsed_seconds'] = round((utcnow()-now).total_seconds(),1)
        if state=='error':
            failed += 1
            failed_instances.append(f"{instance['name']} (instance={instance['id']}, library={instance['library_id']}, run={run_id}, stage={result.get('stage','unknown')}, cause={visible_run_error(result,error_type)})")
        else:
            completed += 1
        next_run = next_collection_run(instance)
        if retry_after:
            next_run = instance['next_run']
        if kind in ('preview','visibility'):
            next_run = instance['next_run']
        # Failures remain visible; the configured schedule is authoritative.
        with db.transaction() as cur:
            owner = cur.execute('SELECT lease_id FROM collection_instances WHERE id=?',
                                (instance['id'],)).fetchone()
            if not owner or owner[0] != lease:
                continue
            store_finished_run(cur,instance['id'],run_id,kind,state,result,error_type,stamp())
            cur.execute("""UPDATE collection_instances SET state=?,last_run=?,next_run=?,last_error=?,lease_id=NULL,lease_until=NULL,
                requested=CASE WHEN requested='cancel' THEN NULL ELSE requested END,updated_at=?
                WHERE id=? AND lease_id=?""",(state,stamp(),next_run,
                visible_run_error(result,error_type) if state=='error' else None,stamp(),instance['id'],lease))
            if retry_after:
                cur.execute("UPDATE collection_instances SET requested=COALESCE(requested,?) WHERE id=?",(kind,instance['id']))
            if kind=='delete' and state not in ('error','cancelled') and not retry_after:
                cur.execute('DELETE FROM collection_arr_requests WHERE instance_id=?',(instance['id'],))
                cur.execute('DELETE FROM collection_instances WHERE id=?',(instance['id'],))
                group_id = instance.get('group_id') or instance['id']
                if not cur.execute('SELECT id FROM collection_instances WHERE group_id=? OR id=?',(group_id,group_id)).fetchone():
                    cur.execute('DELETE FROM collection_person_choices WHERE group_id=?',(group_id,))
        task_logs(task_id,'warning' if state=='warning' else 'error' if state=='error' else 'info',
            f"Collection {instance['name']} finished instance={instance['id']} library={instance['library_id']} server={server['name'] if server else 'unknown'} run={run_id} state={state} stage={result.get('stage','unknown')} cause={visible_run_error(result,error_type) if state=='error' else 'none'}",
            details=result if is_debug_mode_enabled() else {key:result[key] for key in ('stage','elapsed_seconds','outcome','present','missing','arr_requests','errors','warnings','diagnostics','spotlight') if key in result})
    task_logs(task_id,'info',f'Collections: completed={completed} failed={failed} considered={len(candidates)}')
    return {'status':'error' if failed else 'ok', 'error':f"{failed} collection(s) failed: {'; '.join(failed_instances)}" if failed else None,
            'completed':completed,'failed':failed}
