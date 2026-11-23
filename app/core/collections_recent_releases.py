from core.collections_ordering import order_media
"""Local releases selected by original language or country of production."""
import json
import re
import os
import time
import uuid
from datetime import timedelta

from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter
from core.collections_memoria_source import MemoriaSource
from core.collections_repository import CollectionRunCancelled, collection_settings, recent_collection_name, stamp, utcnow
from core.error_reporting import log_handled_failure
from secret_store import decrypt_secret

# Language groups additionally include titles from other production countries.
COUNTRY_LANGUAGES = {'FR':{'fr'}, 'US':{'en'}, 'GB':{'en'}, 'DE':{'de'},
                     'ES':{'es','ca','eu','gl'}, 'IT':{'it'},
                     'CA':{'en','fr'}, 'BE':{'fr','nl','de'}, 'CH':{'de','fr','it','rm'}}


class LanguageAnalysisDeferred(Exception):
    """Continue uncached lookups on a later run without losing cached progress."""


class OriginalLanguageSource(MemoriaSource):
    max_lookup_seconds = 120
    max_lookup_requests = 150

    def tmdb(self, path, **params):
        started=getattr(self,'lookup_started',None)
        if started is None:
            self.lookup_started=time.monotonic()
            self.lookup_requests=0
        if self.lookup_requests>=self.max_lookup_requests or time.monotonic()-self.lookup_started>=self.max_lookup_seconds:
            raise LanguageAnalysisDeferred()
        self.lookup_requests+=1
        return super().tmdb(path,**params)

    def origin_metadata(self, media_type, row):
        identifier = str(row.get('tmdb') or '')
        if not identifier.isdigit() or int(identifier)<=0:
            identities = set()
            # TMDb Find supports TVDB identities for TV, not movies.
            for provider in (('imdb',) if media_type=='movie' else ('imdb','tvdb')):
                value = str(row.get(provider) or '')
                if not re.fullmatch(r'tt[0-9]+' if provider=='imdb' else r'[1-9][0-9]*',value):continue
                data = self.tmdb('/find/'+value,external_source=provider+'_id')
                matches = data.get('movie_results' if media_type=='movie' else 'tv_results',[])
                if not isinstance(matches,list):raise ValueError('collections.media_identity_failed')
                identities.update(item['id'] for item in matches if isinstance(item,dict) and type(item.get('id')) is int and item['id']>0)
            if len(identities)!=1: raise ValueError('collections.media_identity_failed')
            identifier = str(next(iter(identities)))
        key = json.dumps(['release-origin-v2',media_type,int(identifier)])
        cached = self.db.query_one('SELECT data_json FROM collection_discovery_cache WHERE cache_key=? AND updated_at>?',
            (key,stamp(utcnow()-timedelta(days=30)))) if self.db else None
        if cached: return json.loads(cached['data_json'])
        details = self.tmdb('/'+media_type+'/'+identifier)
        language = str(details.get('original_language') or '').lower()
        if details.get('id')!=int(identifier):
            raise ValueError('collections.original_language_unknown')
        metadata={'language':language if len(language)==2 and language.isalpha() else '',
                  'countries':[*(details.get('production_countries') or []),*(details.get('origin_country') or [])]}
        if self.db:
            self.db.execute('INSERT INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at',
                (key,json.dumps(metadata),stamp()))
        return metadata

    def original_language(self, media_type, row):
        language=self.origin_metadata(media_type,row)['language']
        if not language:raise ValueError('collections.original_language_unknown')
        return language


def matches_country(row, country):
    from core.collections_continents import COUNTRY_NAMES, normalized
    for field in ('countries','origin_country','production_countries'):
        values=row.get(field) or []
        if isinstance(values,str):values=[values]
        for value in values:
            if isinstance(value,dict):value=value.get('iso_3166_1') or value.get('name') or ''
            if str(value).strip().upper()==country or COUNTRY_NAMES.get(normalized(value))==country:
                return True
    return False


def run_recent_releases(db, instance, *, kind='sync', heartbeat=lambda:None,
                        source_factory=OriginalLanguageSource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    config['_order_seed']=uuid.uuid4().hex
    country=config['country']
    if country not in COUNTRY_LANGUAGES:
        raise ValueError('collections.invalid_country')
    if kind not in ('cleanup','delete') and (config['mode']=='arr' or config['arr_enabled']):
        raise ValueError('collections.releases_no_arr')
    preview=kind=='preview'
    title=recent_collection_name(country,config['language'])
    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    media_type='movie' if library['type'] in ('movie','movies','film','films') else 'tv'
    result={'people':[],'present':0,'missing':0,'arr_requests':0,'warnings':[],'errors':[],
            'preview':preview,'diagnostics':{'original_languages':sorted(COUNTRY_LANGUAGES[country]),'unknown_languages':[],
                'unresolved_media':[],'selection_sort':config.get('sort'),'selection_limit':config.get('limit')}}
    adapter=source=None
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
        row=db.query_one("SELECT * FROM collection_objects WHERE instance_id=? AND person_key='recent_releases'",(instance['id'],))
        obj=dict(row) if row else None
        if kind in ('cleanup','delete'):
            if obj and not preview:remove(obj)
            return result
        if kind=='expire':return result
        progress('inventory')
        rows=get_adapter().inventory()
        shared=db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key=decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        if rows:
            source=source_factory(key,config['language']);source.db=db;source.heartbeat=heartbeat
        selected=[]
        deferred=0
        rows=sorted(rows,key=lambda row:(str(row.get('release_date') or row.get('year') or '')[:10],str(row['id'])),reverse=True)
        rows=order_media(rows,config)
        progress('selection')
        for index,row in enumerate(rows,1):
            result['diagnostics']['languages_checked']=index
            heartbeat()
            try:
                if matches_country(row,country):
                    selected.append(row)
                    if config['limit'] and len(selected)>=config['limit'] and not deferred:break
                    continue
                if isinstance(source,OriginalLanguageSource):
                    metadata=source.origin_metadata(media_type,row)
                    language=metadata['language']
                    country_match=matches_country({'countries':metadata['countries']},country)
                    if not language and not country_match:raise ValueError('collections.original_language_unknown')
                else:
                    language=source.original_language(media_type,row)
                    country_match=False
            except CollectionRunCancelled:raise
            except LanguageAnalysisDeferred:
                deferred+=1
                continue
            except Exception as exc:
                result['diagnostics']['unknown_languages'].append(row['id'])
                result['diagnostics']['unresolved_media'].append({'id':row['id'],'title':row['title'],
                    'error_type':type(exc).__name__})
                # Missing external IDs/metadata are already exposed as partial
                # selection warnings. Log unexpected failures as errors.
                known=isinstance(exc,ValueError) and str(exc) in {'collections.media_identity_failed','collections.original_language_unknown'}
                result['diagnostics']['unresolved_media'][-1]['reason']=str(exc) if known else 'collections.execution_failed'
                log_handled_failure('collections.releases.original_language',level='warning' if known else 'error')
                continue
            if country_match or language in COUNTRY_LANGUAGES[country]:selected.append(row)
            if index%25==0:progress('selection')
            if config['limit'] and len(selected)>=config['limit'] and not deferred:
                break
        # Every matching title is eligible; no release-date window or age filter.
        selected=order_media(selected,config)
        if config['limit']:selected=selected[:config['limit']]
        partial=bool(result['diagnostics']['unknown_languages'] or deferred)
        result['diagnostics']['languages_deferred']=deferred
        if deferred:result['warnings'].append('collections.releases_analysis_pending')
        if result['diagnostics']['unknown_languages']:result['warnings'].append('collections.original_language_unknown')
        result['diagnostics'].update(partial=partial,library_total=len(rows))
        result['present']=len(selected)
        publication={'person_key':'recent_releases','name':title,'collection_title':title,'published':False,
            'media':[{'title':row['title'],'tmdb_id':row.get('tmdb'),'media_type':media_type,'present':True,
                'library_item_ids':[row['id']],'arr_status':'not_needed'} for row in selected],
            'selected':[row['title'] for row in selected]}
        result['people'].append(publication)
        if not preview:
            if not selected and partial:
                pass
            elif not selected and not partial and collection_settings(db)['suppress_empty']:
                if obj:remove(obj)
            elif selected or obj and obj['remote_id']:
                if obj is None:
                    identifier=str(uuid.uuid4())
                    db.execute("INSERT INTO collection_objects(id,instance_id,person_key,title) VALUES(?,?,'recent_releases',?)",(identifier,instance['id'],title))
                    obj=dict(db.query_one('SELECT * FROM collection_objects WHERE id=?',(identifier,)))
                def created(remote_id):
                    db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,obj['id']))
                    heartbeat()
                progress('publish')
                warnings=get_adapter().sync(obj,title,selected,{**config,'collection_poster':'recent_releases','preserve_existing':partial,'summary':title+' · VODUM'},created)
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
        if source is not None:source.close()
        if adapter is not None:adapter.close()
