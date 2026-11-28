from core.collections_ordering import order_media
"""Publish locally owned titles ordered by their server addition date."""
import json
import uuid
from datetime import datetime, timezone
from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter
from core.collections_repository import CollectionRunCancelled, collection_settings, recently_added_name


def addition_timestamp(value):
    if value is None:
        return float('-inf')
    if isinstance(value,(int,float)):
        return value
    try:
        parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    except (ValueError,TypeError,OverflowError):
        return float('-inf')


def run_recently_added(db, instance, *, kind='sync', heartbeat=lambda:None,
                        adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    config['_order_seed']=uuid.uuid4().hex
    if kind not in ('cleanup','delete') and (config['mode']=='arr' or config['arr_enabled']):
        raise ValueError('collections.releases_no_arr')
    preview=kind=='preview'
    title=recently_added_name(instance['model'],config['language'])
    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    media_type='movie' if library['type'] in ('movie','movies','film','films') else 'tv'
    result={'people':[],'present':0,'missing':0,'arr_requests':0,'warnings':[],'errors':[],
            'preview':preview,'diagnostics':{}}
    adapter=None
    def progress(stage):
        result['stage']=stage
        reporter=getattr(heartbeat,'report',None)
        if callable(reporter): reporter(result)
        heartbeat()
    def get_adapter():
        nonlocal adapter
        if adapter is None:
            adapter=CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
            adapter.heartbeat=heartbeat
        return adapter
    def remove(obj):
        if obj['remote_id']:get_adapter().delete(obj)
        db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(obj['id'],))
    try:
        row=db.query_one("SELECT * FROM collection_objects WHERE instance_id=? AND person_key='recently_added'",(instance['id'],))
        obj=dict(row) if row else None
        if kind in ('cleanup','delete'):
            if obj and not preview:remove(obj)
            return result
        if kind=='expire':return result
        progress('inventory')
        rows=get_adapter().inventory()
        if any('added_at' not in row for row in rows) or rows and not any(row.get('added_at') is not None for row in rows):
            raise ValueError('collections.inventory_dates_required')
        progress('selection')
        # Addition dates come from the media server, independently of release dates.
        selected=sorted(rows,key=lambda row:(addition_timestamp(row.get('added_at')),str(row['id'])),reverse=True)
        if config['limit']:selected=selected[:config['limit']]
        selected=order_media(selected,config)
        partial=False
        result['diagnostics'].update(partial=False,library_total=len(rows))
        result['present']=len(selected)
        publication={'person_key':'recently_added','name':title,'collection_title':title,'published':False,
            'media':[{'title':row['title'],'tmdb_id':row.get('tmdb'),'media_type':media_type,'present':True,
                'library_item_ids':[row['id']],'arr_status':'not_needed'} for row in selected],
            'selected':[row['title'] for row in selected]}
        result['people'].append(publication)
        if not preview:
            if not selected and not partial and collection_settings(db)['suppress_empty']:
                if obj:remove(obj)
            elif selected or obj and obj['remote_id']:
                if obj is None:
                    identifier=str(uuid.uuid4())
                    db.execute("INSERT INTO collection_objects(id,instance_id,person_key,title) VALUES(?,?,'recently_added',?)",(identifier,instance['id'],title))
                    obj=dict(db.query_one('SELECT * FROM collection_objects WHERE id=?',(identifier,)))
                def created(remote_id):
                    db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,obj['id']))
                    heartbeat()
                progress('publish')
                warnings=get_adapter().sync(obj,title,selected,{**config,'collection_poster':'recently_added','preserve_existing':partial,'summary':title+' · VODUM'},created)
                result['warnings'].extend(warnings or [])
                db.execute("UPDATE collection_objects SET state='synced',title=? WHERE id=?",(title,obj['id']))
                publication['published']=True
        result['outcome']='preview' if preview else 'published' if publication['published'] else 'empty'
        progress('complete')
        return result
    except CollectionRunCancelled as exc:
        exc.result=result
        raise
    finally:
        if adapter is not None:adapter.close()
