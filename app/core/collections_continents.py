"""Five continental collections built exclusively from the selected local library."""
import json
import os
import time
import unicodedata
import uuid
from pathlib import Path

from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter, CollectionOwnershipError
from core.collections_ordering import order_media
from core.collections_repository import CollectionRunCancelled, collection_settings
from core.collections_streaming_source import StreamingSource
from secret_store import decrypt_secret

CONTINENTS={'africa':'Africa','americas':'Americas','asia':'Asia','europe':'Europe','oceania':'Oceania'}
GEOGRAPHY=json.loads((Path(__file__).resolve().parents[1]/'data'/'continent_countries.json').read_text(encoding='utf-8'))


def normalized(value):
    return ''.join(char for char in unicodedata.normalize('NFKD',str(value)).casefold() if char.isalnum())


COUNTRY_NAMES={normalized(name):code for name,code in GEOGRAPHY['names'].items()}
COUNTRY_NAMES.update({'usa':'US','unitedstatesofamerica':'US','uk':'GB','southkorea':'KR','northkorea':'KP','ussr':'RU','sovietunion':'RU'})


def continent_regions(values):
    regions=set()
    unknown=False
    for value in values:
        if isinstance(value,dict):value=value.get('iso_3166_1') or value.get('name') or ''
        code=str(value).strip().upper()
        if code not in GEOGRAPHY['countries']:code=COUNTRY_NAMES.get(normalized(value))
        region=GEOGRAPHY['countries'].get(code)
        if region:regions.add(region)
        else:unknown=True
    return regions,unknown


class OriginLookupDeferred(Exception):
    """Only uncached network lookups are subject to the per-run budget."""


class ContinentOriginSource(StreamingSource):
    deadline=float('inf')
    origin_fetches=0

    def before_lookup(self):
        if time.monotonic()>=self.deadline:
            raise OriginLookupDeferred()

    def countries(self,row,kind):
        identifier=str(row.get('tmdb') or '')
        if not identifier.isdigit() or int(identifier)<=0:
            identifier=None
            for provider in ('imdb','tvdb'):
                value=row.get(provider)
                if not value:continue
                def resolve():
                    self.before_lookup()
                    data=self.tmdb('/find/'+str(value),external_source=provider+'_id')
                    matches=data.get('movie_results' if kind=='movie' else 'tv_results')
                    if not isinstance(matches,list) or len(matches)!=1 or type(matches[0].get('id')) is not int or matches[0]['id']<=0:
                        raise ValueError('collections.continents_origin_unknown')
                    return matches[0]['id']
                try:
                    identifier=self.cached(['continent-identity-v1',kind,provider,str(value)],24*30,resolve)
                    break
                except (CollectionRunCancelled,OriginLookupDeferred):raise
                except Exception:continue
            if not identifier:raise ValueError('collections.continents_origin_unknown')
        def load():
            self.before_lookup()
            data=self.tmdb('/'+kind+'/'+str(identifier))
            if data.get('id')!=int(identifier):raise ValueError('collections.continents_origin_unknown')
            countries=[*(data.get('production_countries') or []),*(data.get('origin_country') or [])]
            if not countries:raise ValueError('collections.continents_origin_unknown')
            self.origin_fetches+=1
            return countries
        return self.cached(['continent-origin-v1',kind,int(identifier)],24*30,load)


def run_continents(db,instance,*,kind='sync',heartbeat=lambda:None,adapter_factory=media_adapter,
                   source_factory=ContinentOriginSource,origin_budget_seconds=120):
    config=json.loads(instance['config_json'])
    if config.get('arr_enabled') or config['mode']=='arr':raise ValueError('collections.releases_no_arr')
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
        if kind in ('cleanup','delete'):
            for obj in objects:
                heartbeat()
                if obj['state']!='deleted':remove(obj)
            result.update(stage='complete',outcome='empty');return result
        if kind=='expire':return result
        rows=get_adapter().inventory()
        shared=db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key=decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        grouped={region:[] for region in CONTINENTS}
        unknown=deferred=0
        first_deferred=None
        deadline=time.monotonic()+origin_budget_seconds
        progress_key=json.dumps(['continent-origin-progress-v1',instance['id'],getattr(get_adapter(),'generation',None)])
        progress_row=db.query_one('SELECT data_json FROM collection_discovery_cache WHERE cache_key=?',(progress_key,))
        cursor=json.loads(progress_row['data_json']).get('next_media_id') if progress_row else None
        start=next((index for index,row in enumerate(rows) if str(row['id'])==cursor),0)
        work_rows=rows[start:]+rows[:start]
        progress('classify_countries')
        for row in work_rows:
            heartbeat()
            countries=[*(row.get('countries') or []),*(row.get('origin_country') or []),*(row.get('production_countries') or [])]
            try:
                if not countries:
                    if not key:raise ValueError('collections.continents_origin_unknown')
                    if source is None:
                        source=source_factory(key,config['language']);source.db=db;source.heartbeat=heartbeat;source.deadline=deadline
                    countries=source.countries(row,media_type)
                regions,incomplete=continent_regions(countries)
                if not regions or incomplete:unknown+=1
                for region in regions:grouped[region].append(row)
            except CollectionRunCancelled:raise
            except OriginLookupDeferred:
                deferred+=1
                if first_deferred is None:first_deferred=str(row['id'])
            except Exception:unknown+=1
        partial=unknown>0 or deferred>0
        result['diagnostics'].update(library_total=len(rows),origin_unknown=unknown,origin_deferred=deferred,partial=partial)
        if unknown:result['warnings'].append('collections.continents_origin_unknown')
        if deferred:
            result['warnings'].append('collections.continents_origin_pending')
            if not preview:
                from core.collections_repository import stamp
                db.execute('''INSERT INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES(?,?,?)
                    ON CONFLICT(cache_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at''',
                    (progress_key,json.dumps({'next_media_id':first_deferred}),stamp()))
                # Resume on the configured schedule or a manual launch.
                # Immediate self-queuing bypasses that schedule.
        elif progress_row and not preview:
            db.execute('DELETE FROM collection_discovery_cache WHERE cache_key=?',(progress_key,))
        inventory_order={str(row['id']):index for index,row in enumerate(rows)}
        for region,title in CONTINENTS.items():
            progress('publish')
            stable=sorted({str(row['id']):row for row in grouped[region]}.values(),key=lambda row:inventory_order[str(row['id'])])
            selected=order_media(stable,config)
            if config['limit']:selected=selected[:config['limit']]
            object_key='continent:'+region
            obj=next((row for row in objects if row['person_key']==object_key),None)
            publication={'person_key':object_key,'name':title,'collection_title':title,'published':False,
                'selected':[row['title'] for row in selected],
                'media':[{'title':row['title'],'tmdb_id':row.get('tmdb'),'media_type':media_type,
                          'present':True,'library_item_ids':[row['id']],'arr_status':'not_needed'} for row in selected]}
            result['people'].append(publication)
            result['present']+=len(selected)
            if preview:continue
            if not selected and partial:continue
            if not selected and collection_settings(db)['suppress_empty']:
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
                    {**config,'publication_budget_seconds':30,'collection_poster':'continent_'+region,'summary':title+' · VODUM',
                     'preserve_existing':partial,'_defer_order':deferred>0},created) or [])
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
