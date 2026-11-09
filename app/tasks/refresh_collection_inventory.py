"""One complete inventory per library, shared by every collection configuration."""
import time
import requests
from datetime import datetime, timedelta

from core.collection_inventory import refresh_library, inventory_failure, inventory_connection_cause, mark_inventory_failed
from core.collections_repository import stamp
from core.server_page_queries import LIBRARY_TYPE_SQL
from core.error_reporting import log_handled_failure
from core.server_cooldown import should_skip_unreachable_server
from tasks_engine import task_logs


def run(task_id, db):
    started = time.monotonic()
    run_id = db.execute('INSERT INTO collection_inventory_runs(started_at) VALUES(?)',(stamp(),)).lastrowid
    summaries,failures = [],0
    unavailable_servers = {}
    skipped = 0
    hard_failures = 0
    try:
        libraries = db.query(f'''SELECT l.*, {LIBRARY_TYPE_SQL} AS normalized_type
            FROM libraries l JOIN servers s ON s.id=l.server_id
            WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
              AND EXISTS (SELECT 1 FROM collection_instances c
                          WHERE c.library_id=l.id AND c.retired=0)
            ORDER BY s.id,l.id''')
        for row in libraries:
            library = dict(row)
            if library['normalized_type'] not in ('movie','shows'):
                continue
            server = dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
            if should_skip_unreachable_server(server):
                skipped += 1
                continue
            if library['server_id'] in unavailable_servers:
                failures += 1
                skipped += 1
                mark_inventory_failed(db,library['id'],unavailable_servers[library['server_id']])
                continue
            task_logs(task_id,'info',f"Library inventory started server={library['server_id']} library={library['id']}")
            try:
                summary = refresh_library(db,server,library)
                summaries.append(summary)
                task_logs(task_id,'success',f"Library inventory completed library={library['id']}",details=summary)
            except Exception as exc:
                failures += 1
                if not getattr(exc,'inventory_stage',None): mark_inventory_failed(db,library['id'],exc)
                status = getattr(getattr(exc,'response',None),'status_code',None)
                reason = inventory_failure(exc)
                transient = reason == 'collections.inventory_connection_failed' or (
                    isinstance(exc, requests.HTTPError) and isinstance(status, int) and (status in (408, 429) or 500 <= status < 600)
                )
                warning = transient or reason == 'collections.inventory_invalid'
                if not warning:
                    hard_failures += 1
                if status == 429 or reason in ('collections.inventory_connection_failed',
                                               'collections.inventory_tls_failed','collections.inventory_auth_failed'):
                    unavailable_servers[library['server_id']] = exc
                if not warning:
                    log_handled_failure('collections.inventory.refresh',level='error',
                        library_id=library['id'],server_id=library['server_id'])
                task_logs(task_id,'warning' if warning else 'error',
                    f"Library inventory not refreshed for {server['name']} / {library['name']}",
                    details={'reason':reason,'error_type':type(exc).__name__,
                        'server_id':server['id'],'server_name':server['name'],
                        'library_id':library['id'],'library_name':library['name'],
                        'connection_cause':inventory_connection_cause(exc),
                        'stage':getattr(exc,'inventory_stage','connection'),'http_status':status if isinstance(status,int) else None})
        return {'status':'error' if hard_failures else 'warning' if failures or skipped else 'ok',
                'error':'collections.inventory_unavailable' if hard_failures else None,
                'libraries':len(summaries),'failures':failures,'skipped':skipped,'duration_seconds':round(time.monotonic()-started,3)}
    finally:
        duration = round(time.monotonic()-started,3)
        db.execute('''UPDATE collection_inventory_runs SET finished_at=?,duration_seconds=?,libraries=?,media_count=?,failures=? WHERE id=?''',
            (stamp(),duration,len(summaries),sum(row['media_count'] for row in summaries),failures,run_id))
        # Schedule from completion, including partial failures, rather than from
        # the previous start. The normal success handler uses the same interval.
        next_run = (datetime.now()+timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')
        db.execute('UPDATE tasks SET next_run=?,next_retry_at=NULL WHERE id=?',(next_run,task_id))
        task_logs(task_id,'warning' if failures or skipped else 'success',f"Library inventory finished duration={duration}s libraries={len(summaries)} failures={failures} skipped={skipped}; next run in 12h")
