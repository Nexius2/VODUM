"""Resumable regional catalog acquisition through the selected library's Arr route."""
import json
import time
from core.collections_arr import CollectionArr, failure_detail
from core.collections_repository import CollectionRunCancelled, stamp
from core.collections_platforms_catalog import PLATFORMS


def acquire_platform_catalogs(db,instance,library,config,inventory,source,provider_ids,result,
                             *,preview=False,heartbeat=lambda:None,budget_seconds=60,arr_factory=CollectionArr):
    result.setdefault('arr_details',[]);result.setdefault('arr_planned',0)
    try:arr=arr_factory(db,library,config,heartbeat=heartbeat)
    except CollectionRunCancelled:raise
    except Exception as exc:
        detail=failure_detail(exc,None,{'id':0,'title':library['name']},'preflight')
        result['warnings'].append('collections.arr_server_offline' if detail['reason']=='arr_server_offline' else 'collections.arr_blocked')
        result['arr_details'].append(detail)
        return
    kind='movie' if library['type'] in ('movie','movies','film','films') else 'tv'
    platforms=[key for key in config['platforms'] if provider_ids.get(key)]
    cache_key=json.dumps(['platform-arr-progress-v1',instance['id'],config['country'],platforms,
                          config.get('limit',0),config.get('arr_server')])
    saved=db.query_one('SELECT data_json FROM collection_discovery_cache WHERE cache_key=?',(cache_key,))
    cursor=json.loads(saved['data_json']) if saved and not preview else {'platform':0,'page':1,'offset':0}
    by_tmdb={str(row['tmdb']) for row in inventory if row.get('tmdb')}
    by_external={p:{str(row[p]) for row in inventory if not row.get('tmdb') and row.get(p)} for p in ('imdb','tvdb')}
    unidentified=any(not any(row.get(p) for p in ('tmdb','imdb','tvdb')) for row in inventory)
    deadline=time.monotonic()+budget_seconds
    progressed=0;blocked=False;seen=set()
    result['diagnostics'].setdefault('providers',[])
    while cursor['platform']<len(platforms) and not blocked:
        if time.monotonic()>=deadline:break
        platform=platforms[cursor['platform']]
        try:
            data=source.catalog_page(config['country'],kind,provider_ids[platform],cursor['page'])
        except CollectionRunCancelled:raise
        except Exception as exc:
            result['warnings'].append('collections.platforms_source_failed')
            result['diagnostics']['providers'].append({'id':'platform_catalog_'+platform,
                'name':PLATFORMS[platform]['name'],'state':'warning',
                'failure':{'provider':'tmdb','country':config['country'],'media_type':kind,
                    'stage':'catalog','error_type':type(exc).__name__,
                    'reason':'platforms_catalog_too_large' if str(exc)=='collections.platforms_catalog_too_large' else 'platforms_source_failed'}})
            blocked=True;break
        diagnostic={'id':'platform_catalog_'+platform,'name':PLATFORMS[platform]['name'],
            'state':'success','count':data['total_results'],'page':cursor['page'],'total_pages':data['total_pages']}
        result['diagnostics']['providers'].append(diagnostic)
        rows=data['results']
        while cursor['offset']<len(rows):
            if time.monotonic()>=deadline:break
            position=(cursor['page']-1)*20+cursor['offset']
            if config['limit'] and position>=config['limit']:break
            credit=rows[cursor['offset']];identifier=str(credit['id'])
            heartbeat()
            title=credit.get('title') or credit.get('name')
            media={'tmdb_id':credit['id'],'title':title,'media_type':kind,'present':False,
                   'library_item_ids':[],'arr_status':'not_requested'}
            stage='identity'
            try:
                present=identifier in by_tmdb
                external={}
                if not present and (any(by_external.values()) or kind=='tv'):
                    external=source.media_external_ids(kind,credit['id'])
                    present=any(str(external.get(p+'_id') or '') in ids for p,ids in by_external.items())
                if present:
                    media.update(present=True,arr_status='not_needed')
                elif unidentified:
                    media['arr_status']='identity_failed'
                    result['warnings'].append('collections.media_identity_failed:'+identifier)
                elif identifier not in seen:
                    result['missing']+=1
                    arr_id=credit['id'] if kind=='movie' else external.get('tvdb_id')
                    if not arr_id:
                        media['arr_status']='no_tvdb'
                        result['warnings'].append('collections.arr_no_tvdb:'+identifier)
                    else:
                        stage='lookup'
                        status=arr.submit(instance['id'],arr_id,preview=preview)
                        media['arr_status']=status
                        result['arr_requests']+=int(status=='added')
                        result['arr_planned']+=int(status=='planned')
                        if status in ('pending','not_found','excluded'):
                            result['warnings'].append('collections.'+{'pending':'arr_pending','not_found':'arr_not_found','excluded':'arr_filtered'}[status])
                    seen.add(identifier)
            except CollectionRunCancelled:raise
            except Exception as exc:
                media['arr_status']='failed'
                detail=failure_detail(exc,arr,{'id':credit['id'],'title':title},stage if stage=='identity' else getattr(arr,'stage','lookup'))
                result['arr_details'].append(detail)
                result['warnings'].append('collections.arr_media_failed:'+identifier)
                blocked=bool(getattr(exc,'connection_error',None) or detail['reason']=='arr_add_uncertain' or
                    detail['http_status'] in (401,403,429,502,503,504))
            publication=next((p for p in result['people'] if p['person_key']=='platform:'+config['country']+':'+platform),None)
            if publication is not None and not media['present']:publication['media'].append(media)
            if blocked:break  # Retry this uncertain item; Arr's durable claim prevents duplicate adds.
            cursor['offset']+=1;progressed+=1
        if blocked or time.monotonic()>=deadline:break
        if config['limit'] and (cursor['page']-1)*20+cursor['offset']>=config['limit'] or cursor['page']>=data['total_pages']:
            cursor={'platform':cursor['platform']+1,'page':1,'offset':0}
        elif cursor['offset']>=len(rows):
            cursor.update(page=cursor['page']+1,offset=0)
    pending=cursor['platform']<len(platforms)
    result['diagnostics']['catalog_acquisition_pending']=pending
    if pending:result['warnings'].append('collections.arr_pending')
    if not preview:
        if pending:
            db.execute('''INSERT INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES(?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at''',
                (cache_key,json.dumps(cursor),stamp()))
            if progressed and not blocked:
                db.execute("UPDATE collection_instances SET requested='sync' WHERE id=? AND enabled=1 AND retired=0 AND requested IS NULL",(instance['id'],))
        else:db.execute('DELETE FROM collection_discovery_cache WHERE cache_key=?',(cache_key,))
