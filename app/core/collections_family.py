from core.collections_ordering import order_media
"""Family collection drawn exclusively from the selected local library."""
import json
import uuid
from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter
from core.collections_repository import CollectionRunCancelled, collection_settings, family_collection_name


def family_genres(genres):
    import unicodedata
    names={''.join(c for c in unicodedata.normalize('NFKD',str(value).lower()) if not unicodedata.combining(c)).strip() for value in (genres or [])}
    return bool(names & {'family','famille','familial','familie','familienfilm','familien','familia','famiglia','kids','enfants','children','infantil','bambini'})


def rating(value):
    try:return float(value or 0)
    except (ValueError,TypeError):return 0


def run_family(db, instance, *, kind='sync', heartbeat=lambda:None,
                        adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    config['_order_seed']=uuid.uuid4().hex
    if kind not in ('cleanup','delete') and (config['mode']=='arr' or config['arr_enabled']):
        raise ValueError('collections.releases_no_arr')
    preview=kind=='preview'
    title=family_collection_name(config['language'])
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
        row=db.query_one("SELECT * FROM collection_objects WHERE instance_id=? AND person_key='family'",(instance['id'],))
        obj=dict(row) if row else None
        if kind in ('cleanup','delete'):
            if obj and not preview:remove(obj)
            return result
        if kind=='expire':return result
        progress('inventory')
        rows=get_adapter().inventory()
        progress('selection')
        eligible=[row for row in rows if family_genres(row.get('genres'))]
        chart=config.get('family_chart','top')
        if chart=='latest':
            eligible.sort(key=lambda row:(str(row.get('release_date') or row.get('year') or '')[:10],str(row['id'])),reverse=True)
        else:
            eligible.sort(key=lambda row:(rating(row.get('rating')),str(row['id'])),reverse=True)
        selected=[]
        partial=False
        checked=0
        for row in eligible:
            heartbeat()
            checked+=1
            if config.get('required_audio_language'):
                try:
                    if not get_adapter().has_audio(row,config['required_audio_language']):continue
                except CollectionRunCancelled:raise
                except Exception:
                    partial=True
                    result['warnings'].append('collections.family_audio_unknown')
                    continue
            selected.append(row)
            if config['limit'] and len(selected)>=config['limit']:break
        selected=order_media(selected,config)
        result['warnings']=list(dict.fromkeys(result['warnings']))
        result['diagnostics'].update(partial=partial,library_total=len(rows),candidates_checked=checked)
        result['present']=len(selected)
        publication={'person_key':'family','name':title,'collection_title':title,'published':False,
            'media':[{'title':row['title'],'tmdb_id':row.get('tmdb'),'media_type':media_type,'present':True,
                'library_item_ids':[row['id']],'arr_status':'not_needed'} for row in selected],
            'selected':[row['title'] for row in selected]}
        result['people'].append(publication)
        if not preview:
            if partial:
                pass  # An unknown audio track must not introduce an unverified member.
            elif not selected and not partial and collection_settings(db)['suppress_empty']:
                if obj:remove(obj)
            elif selected or obj and obj['remote_id']:
                if obj is None:
                    identifier=str(uuid.uuid4())
                    db.execute("INSERT INTO collection_objects(id,instance_id,person_key,title) VALUES(?,?,'family',?)",(identifier,instance['id'],title))
                    obj=dict(db.query_one('SELECT * FROM collection_objects WHERE id=?',(identifier,)))
                def created(remote_id):
                    db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,obj['id']))
                    heartbeat()
                progress('publish')
                warnings=get_adapter().sync(obj,title,selected,{**config,'collection_poster':'family','preserve_existing':partial,'summary':title+' · VODUM'},created)
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
