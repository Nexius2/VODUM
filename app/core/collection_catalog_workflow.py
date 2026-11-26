"""Administrative catalogue preparation in the existing Collections worker."""
import copy
import hashlib
import json
import os
import time
import uuid
from datetime import timedelta
from core.collection_lists import read_cursor
from core.collection_list_catalog_review import DATA,content_digest,catalog_review,prepare_catalog,migration_preview
from core.collection_list_migration import migrate_franchise_catalog
from core.collections_repository import stamp,utcnow


def seed_catalog():
    return json.loads((DATA/'collection_lists.json').read_text(encoding='utf-8'))


def workflow_status(db):
    seed=seed_catalog()
    with read_cursor(db) as cur:
        row=cur.execute('SELECT * FROM collection_catalog_preparation WHERE id=1').fetchone()
    if not row:
        return {'state':'not_started','catalog':seed,'report':{},'error':None,'digest':content_digest(seed),'outdated':False}
    return {'state':row['state'],'catalog':json.loads(row['catalog_json']),
            'report':json.loads(row['report_json']),'error':row['error'],
            'digest':content_digest(json.loads(row['catalog_json'])),
            'outdated':row['source_digest']!=content_digest(seed)}


def request_preparation(db):
    seed=seed_catalog();digest=content_digest(seed)
    with db.transaction() as cur:
        row=cur.execute('SELECT * FROM collection_catalog_preparation WHERE id=1').fetchone()
        if row and row['lease_until'] and row['lease_until']>stamp():
            raise ValueError('collections.busy')
        if not row or row['source_digest']!=digest:
            cur.execute("INSERT OR REPLACE INTO collection_catalog_preparation(id,source_digest,catalog_json,state) VALUES(1,?,?,'pending')",(digest,json.dumps(seed)))
        else:
            cur.execute("UPDATE collection_catalog_preparation SET state='pending',lease_id=NULL,lease_until=NULL,error=NULL WHERE id=1")


def process_preparation(db, *, source_factory=None):
    lease=str(uuid.uuid4())
    with db.transaction() as cur:
        row=cur.execute("SELECT * FROM collection_catalog_preparation WHERE id=1 AND (state='pending' OR (state='running' AND lease_until<=?))",(stamp(),)).fetchone()
        if not row:return None
        cur.execute("UPDATE collection_catalog_preparation SET state='running',lease_id=?,lease_until=? WHERE id=1",(lease,stamp(utcnow()+timedelta(minutes=5))))
        catalog=json.loads(row['catalog_json'])
    source=None
    try:
        if source_factory is None:
            from core.collections_memoria_source import MemoriaSource
            from secret_store import decrypt_secret
            from requests.adapters import HTTPAdapter
            shared=db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
            key=decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
            source=MemoriaSource(key,'en')
            source.http.mount('https://',HTTPAdapter(max_retries=0))
        else:source=source_factory()
        deadline=time.monotonic()+60
        class BoundedResolver:
            def tmdb(self,*args,**kwargs):
                if time.monotonic()>=deadline:raise ValueError('request_budget')
                return source.tmdb(*args,**kwargs)
        prepared,report=prepare_catalog(catalog,BoundedResolver(),max_requests=25)
        unresolved=report['unresolved']
        state='pending' if unresolved and all(row['code']=='request_budget' for row in unresolved) else 'needs_review' if not unresolved else 'incomplete'
        with db.transaction() as cur:
            cur.execute("""UPDATE collection_catalog_preparation SET catalog_json=?,report_json=?,state=?,
                lease_id=NULL,lease_until=NULL,error=NULL WHERE id=1 AND lease_id=?""",
                (json.dumps(prepared),json.dumps(report),state,lease))
        return state
    except Exception as exc:
        code='collections.tmdb_key_required' if str(exc)=='collections.tmdb_key_required' else 'lists.catalog_prepare_failed'
        db.execute("UPDATE collection_catalog_preparation SET state='error',error=?,lease_id=NULL,lease_until=NULL WHERE id=1 AND lease_id=?",(code,lease))
        return 'error'
    finally:
        if source is not None:source.close()


def _review_candidate(db):
    status=workflow_status(db)
    if status['outdated'] or status['state'] not in ('needs_review','activated'):
        raise ValueError('lists.catalog_not_prepared')
    catalog=copy.deepcopy(status['catalog']);catalog['status']='ready'
    catalog['review']={'content_digest':content_digest(catalog),'source_coverage_verified':True}
    if not catalog_review(catalog)['eligible']:raise ValueError('lists.catalog_not_prepared')
    return catalog


def activation_preview(db):
    catalog=_review_candidate(db);plan=migration_preview(db,catalog)
    token=hashlib.sha256(json.dumps([content_digest(catalog),plan],sort_keys=True).encode()).hexdigest()
    return catalog,plan,token


def activate_catalog(db, token, *, confirmed=False,coverage=False):
    if not (confirmed is True and coverage is True):
        raise ValueError('lists.delete_confirmation_required')
    reviewed=workflow_status(db)
    catalog,plan,current=activation_preview(db)
    if not plan['eligible'] or token!=current or reviewed['digest']!=content_digest(catalog):raise ValueError('lists.catalog_plan_changed')
    lease=str(uuid.uuid4())
    with db.transaction() as cur:
        row=cur.execute('SELECT * FROM collection_catalog_preparation WHERE id=1').fetchone()
        if (not row or row['state'] not in ('needs_review','activated')
                or content_digest(json.loads(row['catalog_json']))!=content_digest(catalog)):
            raise ValueError('lists.catalog_plan_changed')
        cur.execute("UPDATE collection_catalog_preparation SET state='activating',lease_id=?,lease_until=? WHERE id=1",(lease,stamp(utcnow()+timedelta(minutes=5))))
    try:
        result=migrate_franchise_catalog(db,catalog)
    except Exception:
        db.execute("UPDATE collection_catalog_preparation SET state='needs_review',lease_id=NULL,lease_until=NULL WHERE id=1 AND lease_id=?",(lease,))
        raise
    db.execute("UPDATE collection_catalog_preparation SET state='activated',lease_id=NULL,lease_until=NULL WHERE id=1 AND lease_id=?",(lease,))
    return result
