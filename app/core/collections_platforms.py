"""All locally owned media available on the selected regional subscriptions."""
import json
import os
import time
import uuid
import unicodedata
from datetime import timedelta
from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter,CollectionOwnershipError
from core.collections_ordering import order_media
from core.collections_repository import CollectionRunCancelled,collection_settings,stamp,utcnow
from core.collections_streaming_source import StreamingSource
from core.collections_platforms_catalog import PLATFORMS,platform_collection_title
from secret_store import decrypt_secret


def normalized_name(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value)).casefold() if c.isalnum())


class PlatformLookupDeferred(Exception):
    pass


class PlatformAvailabilitySource(StreamingSource):
    deadline=float('inf')
    availability_fetches=0

    def before_lookup(self):
        if time.monotonic()>=self.deadline:raise PlatformLookupDeferred()

    def provider_ids(self,country,kind,selected):
        def load():
            self.before_lookup()
            data=self.tmdb('/watch/providers/'+kind,watch_region=country)
            rows=data.get('results')
            if not isinstance(rows,list) or any(not isinstance(row,dict) or type(row.get('provider_id')) is not int or row['provider_id']<=0 or not isinstance(row.get('provider_name'),str) for row in rows):
                raise ValueError('collections.platforms_source_failed')
            return rows
        rows=self.cached(['platform-regional-providers-v1',country,kind],24,load)
        result={}
        for key in selected:
            spec=PLATFORMS[key];names={normalized_name(name) for name in spec['aliases']}
            result[key]={row['provider_id'] for row in rows if row['provider_id'] in spec['ids'] or normalized_name(row['provider_name']) in names}
        return result

    def platforms_for(self,row,kind,provider_ids,country):
        negative_key=json.dumps(['platform-negative-v1',kind,country,row.get('tmdb'),row.get('imdb'),row.get('tvdb')])
        if self.db and self.db.query_one('SELECT cache_key FROM collection_discovery_cache WHERE cache_key=? AND updated_at>?',
                (negative_key,stamp(utcnow()-timedelta(minutes=5)))):
            raise ValueError('collections.platforms_availability_unknown')
        try:return self._platforms_for(row,kind,provider_ids,country)
        except (CollectionRunCancelled,PlatformLookupDeferred):raise
        except Exception:
            if self.db:
                self.db.execute("INSERT INTO collection_discovery_cache VALUES(?,'{}',?) ON CONFLICT(cache_key) DO UPDATE SET updated_at=excluded.updated_at",
                    (negative_key,stamp()))
            raise

    def _platforms_for(self,row,kind,provider_ids,country):
        identifier=str(row.get('tmdb') or '')
        if not identifier.isdigit() or int(identifier)<=0:
            identifier=None
            for provider in ('imdb','tvdb'):
                value=row.get(provider)
                if not value:continue
                def resolve(p=provider,v=value):
                    self.before_lookup()
                    data=self.tmdb('/find/'+str(v),external_source=p+'_id')
                    matches=data.get('movie_results' if kind=='movie' else 'tv_results')
                    if not isinstance(matches,list) or len(matches)!=1 or type(matches[0].get('id')) is not int or matches[0]['id']<=0:
                        raise ValueError('collections.platforms_availability_unknown')
                    return matches[0]['id']
                try:
                    identifier=self.cached(['platform-local-identity-v1',kind,provider,str(value)],24*30,resolve)
                    break
                except (CollectionRunCancelled,PlatformLookupDeferred):raise
                except Exception:continue
            if not identifier:raise ValueError('collections.platforms_availability_unknown')
        def load():
            self.before_lookup()
            data=self.tmdb('/'+kind+'/'+str(identifier)+'/watch/providers')
            results=data.get('results')
            if data.get('id')!=int(identifier) or not isinstance(results,dict):
                raise ValueError('collections.platforms_availability_unknown')
            for region,offers in results.items():
                if not isinstance(offers,dict):raise ValueError('collections.platforms_availability_unknown')
                for field in ('flatrate','ads','free','rent','buy'):
                    values=offers.get(field,[])
                    if not isinstance(values,list) or any(not isinstance(item,dict) or type(item.get('provider_id')) is not int for item in values):
                        raise ValueError('collections.platforms_availability_unknown')
            self.availability_fetches+=1
            return results
        results=self.cached(['platform-local-offers-v1',kind,int(identifier)],24,load)
        offers=(results.get(country) or {}).get('flatrate',[])
        identifiers={item['provider_id'] for item in offers}
        return {key for key,ids in provider_ids.items() if identifiers & ids}

    def catalog_page(self,country,kind,ids,page):
        def load():
            params={'watch_region':country,'with_watch_providers':'|'.join(str(i) for i in sorted(ids)),
                    'with_watch_monetization_types':'flatrate','sort_by':'popularity.desc',
                    'include_adult':'false','page':page}
            if kind=='movie':params['include_video']='true'
            data=self.tmdb('/discover/'+kind,**params)
            rows=data.get('results');pages=data.get('total_pages');total=data.get('total_results')
            if (not isinstance(rows,list) or type(pages) is not int or pages<0 or
                    type(total) is not int or total<0 or data.get('page')!=page or
                    any(not isinstance(row,dict) or type(row.get('id')) is not int or row['id']<=0 or
                        not (row.get('title') or row.get('name')) for row in rows)):
                raise ValueError('collections.platforms_source_failed')
            # Never silently label a truncated 500-page catalog as complete.
            if pages>500:raise ValueError('collections.platforms_catalog_too_large')
            if not rows and total:raise ValueError('collections.platforms_source_failed')
            return data
        return self.cached(['platform-regional-catalog-v1',country,kind,sorted(ids),page,self.language],24,load)


def run_platforms(db,instance,*,kind='sync',heartbeat=lambda:None,adapter_factory=media_adapter,
                   source_factory=PlatformAvailabilitySource,availability_budget_seconds=120):
    config=json.loads(instance['config_json'])
    country=config['country']
    selected_platforms=config['platforms']
    preview=kind=='preview'
    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    media_type='movie' if library['type'] in ('movie','movies','film','films') else 'tv'
    result={'people':[],'present':0,'missing':0,'arr_requests':0,'errors':[],'warnings':[],
            'preview':preview,'diagnostics':{},'stage':'inventory'}
    adapter=source=None
    def get_adapter():
        nonlocal adapter
        if adapter is None:
            adapter=CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
            adapter.heartbeat=heartbeat
        return adapter
    def progress(stage):
        result['stage']=stage
        heartbeat()
        report=getattr(heartbeat,'report',None)
        if callable(report):report(result)
    def remove(obj):
        if obj['remote_id']:get_adapter().delete(obj)
        db.execute("UPDATE collection_objects SET remote_id=NULL,state='deleted' WHERE id=?",(obj['id'],))
    try:
        objects=[dict(row) for row in db.query('SELECT * FROM collection_objects WHERE instance_id=?',(instance['id'],))]
        if kind in ('cleanup','delete') or config['mode']=='arr':
            for obj in objects:
                heartbeat()
                if obj['state']!='deleted' and not preview:remove(obj)
            if kind in ('cleanup','delete'):
                result.update(stage='complete',outcome='empty');return result
        if kind=='expire':return result
        rows=get_adapter().inventory()
        shared=db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key=decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        if not key:raise ValueError('collections.tmdb_key_required')
        deadline=time.monotonic()+availability_budget_seconds
        source=source_factory(key,config['language']);source.db=db;source.heartbeat=heartbeat;source.deadline=deadline
        provider_ids=source.provider_ids(country,media_type,selected_platforms)
        unavailable=[key for key,ids in provider_ids.items() if not ids]
        if unavailable:
            result['warnings'].append('collections.platforms_unavailable')
            result['diagnostics']['unavailable_platforms']=[PLATFORMS[key]['name'] for key in unavailable]
        grouped={key:[] for key in selected_platforms}
        unknown=deferred=0
        uncertain_ids=set()
        first_deferred=None
        progress_key=json.dumps(['platform-availability-progress-v1',instance['id'],country,selected_platforms,getattr(get_adapter(),'generation',None)])
        progress_row=db.query_one('SELECT data_json FROM collection_discovery_cache WHERE cache_key=?',(progress_key,))
        cursor=json.loads(progress_row['data_json']).get('next_media_id') if progress_row else None
        start=next((index for index,row in enumerate(rows) if str(row['id'])==cursor),0)
        work_rows=rows[start:]+rows[:start]
        progress('classify_platforms')
        for row in work_rows if config['mode']!='arr' else []:
            heartbeat()
            try:
                platforms=source.platforms_for(row,media_type,provider_ids,country) if any(provider_ids.values()) else set()
                for platform in platforms:grouped[platform].append(row)
            except CollectionRunCancelled:raise
            except PlatformLookupDeferred:
                deferred+=1
                uncertain_ids.add(str(row['id']))
                if first_deferred is None:first_deferred=str(row['id'])
            except Exception:
                unknown+=1
                uncertain_ids.add(str(row['id']))
        partial=unknown>0 or deferred>0
        result['diagnostics'].update(library_total=len(rows),availability_unknown=unknown,availability_deferred=deferred,partial=partial)
        if unknown:result['warnings'].append('collections.platforms_availability_unknown')
        if deferred:
            result['warnings'].append('collections.platforms_availability_pending')
            if not preview:
                from core.collections_repository import stamp
                db.execute('''INSERT INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES(?,?,?)
                    ON CONFLICT(cache_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at''',
                    (progress_key,json.dumps({'next_media_id':first_deferred}),stamp()))
                fetched=getattr(source,'availability_fetches',0)
                if isinstance(fetched,int) and fetched>0:
                    db.execute("UPDATE collection_instances SET requested='sync' WHERE id=? AND enabled=1 AND retired=0 AND requested IS NULL",(instance['id'],))
                    result['diagnostics']['availability_resume_queued']=True
        elif progress_row and not preview:
            db.execute('DELETE FROM collection_discovery_cache WHERE cache_key=?',(progress_key,))
        # The discovery cursor rotates the scan, not the published ranking.
        inventory_order={str(row['id']):index for index,row in enumerate(rows)}
        for region in selected_platforms:
            title=platform_collection_title(region,country,config['language'])
            progress('publish')
            stable=sorted({str(row['id']):row for row in grouped[region]}.values(),key=lambda row:inventory_order[str(row['id'])])
            selected=order_media(stable,config)
            if config['limit']:selected=selected[:config['limit']]
            object_key='platform:'+country+':'+region
            obj=next((row for row in objects if row['person_key']==object_key),None)
            publication={'person_key':object_key,'name':title,'collection_title':title,'published':False,
                'selected':[row['title'] for row in selected],
                'media':[{'title':row['title'],'tmdb_id':row.get('tmdb'),'media_type':media_type,
                          'present':True,'library_item_ids':[row['id']],'arr_status':'not_needed'} for row in selected]}
            result['people'].append(publication)
            result['present']+=len(selected)
            if preview or config['mode']=='arr':continue
            if not selected and partial and (len(uncertain_ids)==len(rows) or not (obj and obj['remote_id'])):continue
            if not selected and not partial and collection_settings(db)['suppress_empty']:
                if obj and obj['remote_id']:remove(obj)
                continue
            if not selected and not (obj and obj['remote_id']):continue
            if obj is None:
                identifier=str(uuid.uuid4())
                db.execute('INSERT INTO collection_objects(id,instance_id,person_key,title) VALUES(?,?,?,?)',
                           (identifier,instance['id'],object_key,title))
                obj=dict(db.query_one('SELECT * FROM collection_objects WHERE id=?',(identifier,)))
            def created(remote_id):
                db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,obj['id']))
            try:
                result['warnings'].extend(get_adapter().sync(obj,title,selected,
                    {**config,'publication_budget_seconds':30,'collection_poster':'platform_'+region,'summary':title+' · VODUM',
                     'preserve_existing':partial,'preserve_existing_ids':sorted(uncertain_ids),
                     '_defer_order':deferred>0},created) or [])
            except CollectionOwnershipError as exc:
                code=str(exc)
                result['warnings' if code=='collections.title_collision' else 'errors'].append(code)
                conflict={'title':title,'server_name':server.get('name') or str(server['id']),
                          'library_name':library['name'],'library_id':library['id'],**getattr(exc,'conflict',{})}
                publication['conflict']=conflict
                result['diagnostics'].setdefault('conflicts',[]).append(conflict)
                result['diagnostics'].setdefault('providers',[]).append({
                    'id':object_key,'name':title+' · '+str(conflict['server_name'])+' / '+str(library['name']),
                    'state':'warning' if code=='collections.title_collision' else 'error',
                    'failure':{'country':library['name'],'media_type':media_type,'stage':'publication',
                               'error_type':type(exc).__name__,'reason':code.removeprefix('collections.')}})
                continue
            db.execute("UPDATE collection_objects SET state='synced',title=? WHERE id=?",(title,obj['id']))
            publication['published']=True
        if not preview and not partial and not result['errors']:
            active={'platform:'+country+':'+key for key in selected_platforms}
            for old in objects:
                if old['person_key'] not in active and old['state']!='deleted':remove(old)
        if config.get('arr_enabled'):
            from core.collections_platforms_arr import acquire_platform_catalogs
            progress('acquisition')
            acquire_platform_catalogs(db,instance,library,config,rows,source,provider_ids,result,
                preview=preview,heartbeat=heartbeat)
        result['warnings']=list(dict.fromkeys(result['warnings']))
        result.update(outcome='preview' if preview else 'failed' if result['errors'] else 'published' if any(row['published'] for row in result['people']) else 'empty')
        progress('complete')
        return result
    except (CollectionRunCancelled,CollectionOwnershipError) as exc:
        exc.result=result
        raise
    finally:
        if source is not None:source.close()
        if adapter is not None:adapter.close()
