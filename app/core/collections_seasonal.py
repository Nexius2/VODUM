"""One owned collection per selected event, retired outside its local window."""
import json
from datetime import datetime, time, timedelta, timezone
from dateutil.tz import gettz

from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter
from core.collections_repository import utcnow, stamp, CollectionRunCancelled, global_timezone
from core.collections_seasonal_calendar import seasonal_calendar
from core.collections_seasonal_source import SeasonalEventSource
from core.collections_streaming import run_streaming_country
from core.error_reporting import log_handled_failure


def run_seasonal(db,instance,*,kind='sync',heartbeat=lambda:None,source_factory=SeasonalEventSource,
                 adapter_factory=media_adapter,now=None):
    config=json.loads(instance['config_json']);preview=kind=='preview'
    library_scope=db.query_one('SELECT type FROM libraries WHERE id=?',(instance['library_id'],))
    if kind not in ('cleanup','delete') and (not library_scope or library_scope['type'] not in ('movie','movies','film','films')):
        raise ValueError('collections.invalid_library')
    zone=gettz(global_timezone(db))
    clock=(lambda:now) if now is not None else utcnow
    today=clock().astimezone(zone).date()
    calendar=[] if kind in ('cleanup','delete') else seasonal_calendar(config['country'],config['language'],today)
    selected=set() if kind in ('cleanup','delete') else set(config['events'])
    events=[row for row in calendar if row['id'] in selected]
    active={row['id']:row for row in events if row['active'] and row['available']}
    result={'people':[],'present':0,'missing':0,'arr_requests':0,'arr_planned':0,'warnings':[],'errors':[],
            'arr_details':[],'preview':preview,'stage':'cleanup','diagnostics':{'events':events,'providers':[]}}
    adapter=None;inventory=None;children={}
    def get_adapter():
        nonlocal adapter
        if adapter is None:
            library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
            server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
            adapter=CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
            adapter.heartbeat=heartbeat
        return adapter
    def library_rows():
        nonlocal inventory
        if inventory is None:inventory=get_adapter().inventory()
        return inventory
    class SharedAdapter:
        # The orchestrator owns the adapter lifecycle across all active events.
        def inventory(self):return library_rows()
        def close(self):pass
        def __getattr__(self,key):return getattr(get_adapter(),key)
    shared=SharedAdapter()
    def report(event,child):
        children[event]=child
        result['stage']=child.get('stage','selection')
        for key in ('present','missing','arr_requests','arr_planned'):
            result[key]=sum(row.get(key,0) for row in children.values())
        for key in ('people','warnings','errors','arr_details'):
            result[key]=[item for row in children.values() for item in row.get(key,[])]
        result['diagnostics']['providers']=[{**row,'name':name+' · '+row.get('name',row['id'])}
            for name,child in children.items() for row in child.get('diagnostics',{}).get('providers',[])]
        reporter=getattr(heartbeat,'report',None)
        if callable(reporter):reporter(result)
    try:
        objects=[dict(row) for row in db.query('SELECT * FROM collection_objects WHERE instance_id=?',(instance['id'],))]
        for obj in objects:
            heartbeat()
            event=obj['person_key'].removeprefix('seasonal:')
            if kind not in ('cleanup','delete') and event in active:continue
            if not preview:
                if obj['remote_id']:get_adapter().delete(obj)
                db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(obj['id'],))
                db.execute('DELETE FROM collection_seasonal_windows WHERE instance_id=? AND event_key=?',(instance['id'],event))
        if kind in ('cleanup','delete','expire'):
            if not preview:
                if kind in ('cleanup','delete'):db.execute('DELETE FROM collection_seasonal_windows WHERE instance_id=?',(instance['id'],))
                else:db.execute('DELETE FROM collection_seasonal_windows WHERE instance_id=? AND expires_at<=?',(instance['id'],stamp(clock())))
            return result
        for position,(event,window) in enumerate(active.items()):
            end=datetime.combine(datetime.fromisoformat(window['end']).date()+timedelta(days=1),time.min,tzinfo=zone).astimezone(timezone.utc)
            if not preview:
                # Record the deadline before remote mutation, so an interrupted
                # create remains eligible for cleanup when its window ends.
                db.execute('INSERT INTO collection_seasonal_windows(instance_id,event_key,expires_at) VALUES(?,?,?) ON CONFLICT(instance_id,event_key) DO UPDATE SET expires_at=excluded.expires_at',
                    (instance['id'],event,stamp(end)))
            def event_heartbeat():
                heartbeat()
                if clock()>=end:raise CollectionRunCancelled('Seasonal display window ended')
            event_heartbeat.report=lambda child,e=event:report(e,child)
            factory=lambda key,language,e=event:source_factory(key,language,event=e,country=config['country'],
                mode=config['seasonal_source'],inventory=library_rows,sort=config['sort'],
                seed=f"{instance['id']}:{e}:{today.isoformat()}")
            child_instance={**instance,'config_json':json.dumps({**config,'priority':config['priority']+position})}
            try:
                child=run_streaming_country(db,child_instance,kind=kind,heartbeat=event_heartbeat,
                    source_factory=factory,adapter_factory=lambda *args:shared,
                    object_key_override='seasonal:'+event,title_override=window['name'],poster_key_override='seasonal_'+event,uses_tmdb=config['seasonal_source']!='local')
            except CollectionRunCancelled:raise
            except Exception as exc:
                log_handled_failure('collections.seasonal.event',level='error')
                child=children.get(event,{'people':[],'warnings':[],'errors':[]})
                code=str(exc) if str(exc) in ('collections.ownership_failed','collections.title_collision','collections.publication_failed') else 'collections.execution_failed'
                child.setdefault('errors',[]).append(code+':'+event)
            report(event,child)
            if not preview:
                obj=db.query_one("SELECT remote_id FROM collection_objects WHERE instance_id=? AND person_key=?",(instance['id'],'seasonal:'+event))
                if obj and obj['remote_id']:
                    db.execute('INSERT INTO collection_seasonal_windows(instance_id,event_key,expires_at) VALUES(?,?,?) ON CONFLICT(instance_id,event_key) DO UPDATE SET expires_at=excluded.expires_at',
                        (instance['id'],event,stamp(end)))
                else:db.execute('DELETE FROM collection_seasonal_windows WHERE instance_id=? AND event_key=?',(instance['id'],event))
        result['outcome']='preview' if preview else 'failed' if result['errors'] else 'published' if any(row.get('published') for row in result['people']) else 'waiting' if not active else 'empty'
        result['stage']='complete'
        reporter=getattr(heartbeat,'report',None)
        if callable(reporter):reporter(result)
        return result
    except CollectionRunCancelled as exc:
        exc.result=result
        raise
    finally:
        if adapter is not None:adapter.close()
