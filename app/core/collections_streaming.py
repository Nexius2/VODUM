from core.collections_ordering import order_media
from core.collections_posters import streaming_poster_key
"""Publish one ranked, deduplicated country chart per library."""
import json
import os
import time
import uuid

from core.collections_arr import CollectionArr, failure_detail, log_arr_failure
from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter, CollectionOwnershipError
from core.collections_repository import CollectionRunCancelled, collection_settings, stamp, streaming_collection_name, fixed_collection_name, worldwide_collection_name, streaming_title
from core.collections_streaming_source import StreamingSource
from core.error_reporting import log_handled_failure
from secret_store import decrypt_secret


def run_streaming_country(db, instance, *, kind='sync', heartbeat=lambda:None,
                          source_factory=None, adapter_factory=media_adapter,
                          object_key_override=None, title_override=None, uses_tmdb=True, poster_key_override=None):
    config = json.loads(instance['config_json'])
    config['_order_seed']=uuid.uuid4().hex
    preview = kind=='preview'
    library = dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server = dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    media_type = 'movie' if library['type'] in ('movie','movies','film','films') else 'tv'
    worldwide = instance['model']=='streaming_worldwide'
    object_key = object_key_override or instance['model']
    title = title_override or streaming_title(instance['model'],config['language'],config.get('country','FR'),config.get('region','worldwide'),config.get('content_language',''))
    if source_factory is None:
        if worldwide:
            from core.collections_streaming_worldwide import WorldwideStreamingSource
            source_factory = WorldwideStreamingSource
        elif instance['model']=='streaming_country':
            from core.collections_country_availability import CountryAvailabilitySource
            source_factory = CountryAvailabilitySource
        else:
            source_factory = StreamingSource
    result = {'people':[],'present':0,'missing':0,'arr_requests':0,'arr_planned':0,
              'warnings':[],'errors':[],'arr_details':[],'diagnostics':{'providers':[]},'preview':preview}
    adapter = source = None

    def progress(stage):
        result['stage'] = stage
        if source is not None:
            result['diagnostics']['providers'] = source.diagnostics
            if instance['model'] in ('streaming_country','streaming_worldwide') and source.diagnostics:
                coverage = {
                    'direct':sum(p.get('source_kind') in ('platform_chart','worldwide_platform_chart','continent_platform_chart','worldwide_tmdb_streaming','continent_tmdb_streaming','country_tmdb_availability') and p.get('count',0)>0 for p in source.diagnostics),
                    'fallback':sum(p.get('source_kind') in ('justwatch_popularity','worldwide_tmdb_trending') and p.get('count',0)>0 for p in source.diagnostics),
                    'failed':sum(p.get('state')=='error' for p in source.diagnostics),
                }
                result['diagnostics']['coverage'] = coverage
                if stage=='complete' and not coverage['direct'] and coverage['fallback']:
                    if 'collections.streaming_degraded' not in result['warnings']:
                        result['warnings'].append('collections.streaming_degraded')
            for provider in source.diagnostics:
                if provider.get('failure'):
                    code = 'collections.streaming_provider_failed:'+provider['id']
                    target = result['warnings'] if getattr(source,'partial',False) and not result['errors'] else result['errors']
                    if code not in target: target.append(code)
                if provider.get('failures'):
                    code = ('collections.streaming_identity_skipped:' if provider.get('identity_skipped') or provider.get('source_kind','').startswith(('worldwide_','continent_','imdb_','awards_')) else 'collections.streaming_provider_fallback:')+provider['id']
                    if code not in result['warnings']: result['warnings'].append(code)
        reporter = getattr(heartbeat,'report',None)
        if callable(reporter): reporter(result)
        heartbeat()

    def get_adapter():
        nonlocal adapter
        if adapter is None:
            adapter = CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
            adapter.heartbeat = heartbeat
        return adapter

    def remove(obj):
        heartbeat()
        if obj['remote_id']: get_adapter().delete(obj)
        db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(obj['id'],))

    try:
        objects = [dict(row) for row in db.query('SELECT * FROM collection_objects WHERE instance_id=?',(instance['id'],))]
        if kind in ('cleanup','delete') or config['mode']=='arr':
            if not preview:
                for obj in objects:
                    if obj['state']!='deleted' and (object_key_override is None or obj['person_key']==object_key): remove(obj)
            if kind in ('cleanup','delete'):
                result['outcome'] = 'empty'
                return result
        if kind=='expire': return result
        shared = db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1') if uses_tmdb else None
        key = (decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')) if uses_tmdb else None
        source = source_factory(key,config['language'])
        source.db, source.heartbeat = db, heartbeat
        if instance['model']=='streaming_country':
            source.content_language = config.get('content_language') or None
        progress('discovery')
        try:
            candidates = source.discover(config.get('region','worldwide') if worldwide else config['country'],media_type)
        except CollectionRunCancelled: raise
        except Exception as exc:
            log_handled_failure('collections.streaming.discovery',level='error')
            code = str(exc) if str(exc) in ('collections.streaming_incomplete','collections.streaming_empty','collections.streaming_source_invalid','collections.seasonal_sources_unavailable','collections.imdb_source_unavailable','collections.imdb_source_invalid','collections.imdb_invalid_chart','collections.awards_source_unavailable','collections.awards_source_invalid') else 'collections.streaming_unavailable'
            result['errors'].append(code)
            progress('complete')
            return result
        result['diagnostics']['candidates'] = len(candidates)
        partial = bool(getattr(source,'partial',False))
        result['diagnostics']['partial'] = partial
        if partial: result['warnings'].append('collections.streaming_partial')
        if config.get('content_language'):
            filtered = []
            for candidate in candidates:
                heartbeat()
                try:
                    if source.original_language(media_type,candidate)==config['content_language']:
                        filtered.append(candidate)
                except CollectionRunCancelled: raise
                except Exception:
                    partial = True
                    result['warnings'].append('collections.original_language_unknown')
                    log_handled_failure('collections.streaming.content_language',level='error')
            candidates = filtered
            result['diagnostics']['partial'] = partial
            result['diagnostics']['content_language'] = config['content_language']
            if partial and 'collections.streaming_partial' not in result['warnings']:
                result['warnings'].append('collections.streaming_partial')
        fill_local_limit = config['mode']!='arr' and bool(config['limit'])
        acquisition_ids = {row['id'] for row in candidates[:config['limit']]} if fill_local_limit else None
        if config['limit'] and not fill_local_limit:
            candidates = candidates[:config['limit']]
        # Resolve all local identities before publishing or submitting to Arr.
        # A failed lookup must never turn an unknown local title into a download.
        progress('inventory')
        inventory = get_adapter().inventory()
        by_tmdb, by_external = {}, {'imdb':{},'tvdb':{}}
        by_title, by_title_year = {}, {}
        match_titles = getattr(source,'match_local_titles',False) is True
        if match_titles:
            from core.collections_country_availability import local_title_key
            for row in inventory:
                key=local_title_key(row.get('title'))
                if key:
                    by_title.setdefault(key,[]).append(row)
                    if row.get('year'):
                        by_title_year.setdefault((key,str(row['year'])),[]).append(row)
        by_local_id = {str(row['id']):row for row in inventory}
        for row in inventory:
            if row.get('tmdb'): by_tmdb.setdefault(str(row['tmdb']),[]).append(row)
            else:
                for provider in by_external:
                    if row.get(provider): by_external[provider].setdefault(str(row[provider]),[]).append(row)
        selected, missing, media_rows, seen = [], [], [], set()
        missing_candidates = []
        progress('match')
        for candidate_index,credit in enumerate(candidates):
            if fill_local_limit and len(selected)>=config['limit'] and candidate_index>=config['limit']:
                break
            heartbeat()
            matches = [by_local_id[str(identifier)] for identifier in credit.get('library_item_ids',[]) if str(identifier) in by_local_id]
            if not matches: matches = list(by_tmdb.get(str(credit['id']),[]))
            # A verified alternate ID is sufficient even when the library's
            # TMDb lookup failed earlier. Never match contradictory TMDb IDs.
            if not matches:
                for provider,index in by_external.items():
                    if credit.get(provider+'_id'):
                        matches.extend(index.get(str(credit[provider+'_id']),[]))
            if not matches and match_titles:
                key=local_title_key(credit['title'])
                title_matches=by_title_year.get((key,str(credit.get('year') or '')),[])
                if not title_matches and len(by_title.get(key,[]))==1:
                    candidate=by_title[key][0]
                    # A known contradictory year/ID must not match a remake.
                    if not candidate.get('year') or not credit.get('year') or str(candidate['year'])==str(credit['year']):
                        title_matches=[candidate]
                matches=[row for row in title_matches if not row.get('tmdb') or str(row['tmdb'])==str(credit['id'])]
            resolved_only=getattr(source,'match_resolved_inventory_only',False) is True
            if not matches and resolved_only and getattr(source,'local_identity_uncertain',False) is True:
                # An unresolved local item could be this candidate. Preserve
                # existing members and do not declare absence or acquire it.
                partial=True
                result['diagnostics']['partial']=True
                result['warnings'].append('collections.streaming_partial')
                media_rows.append({'tmdb_id':credit['id'],'title':credit['title'],'media_type':media_type,
                    'present':False,'library_item_ids':[],'sources':credit['sources'],
                    'ranks_by_source':credit['ranks_by_source'],'source_kinds':credit['source_kinds'],
                    'buzz_score':credit['buzz_score'],'arr_status':'identity_failed'})
                continue
            if not matches and not resolved_only and any(by_external.values()):
                unresolved = {}
                for provider,index in by_external.items():
                    if credit.get(provider+'_id'):
                        matches.extend(index.get(str(credit[provider+'_id']),[]))
                    elif index:
                        unresolved[provider] = index
                try:
                    if not matches and unresolved:
                        external = source.media_external_ids(media_type,credit['id'])
                        for provider,index in unresolved.items():
                            matches.extend(index.get(str(external.get(provider+'_id') or ''),[]))
                except CollectionRunCancelled: raise
                except Exception as exc:
                    # An unresolved identity says nothing about local absence.
                    # Skip only this candidate, never submit it to Arr, and
                    # preserve existing membership while processing other titles.
                    partial = True
                    result['diagnostics']['partial'] = True
                    result['warnings'].extend(['collections.streaming_partial',
                        'collections.media_identity_failed:'+str(credit['id'])])
                    response = getattr(exc,'response',None)
                    status = getattr(response,'status_code',None)
                    result['diagnostics'].setdefault('identity_failures',[]).append({
                        'tmdb_id':credit['id'],'media_type':media_type,
                        'http_status':status if isinstance(status,int) else None,
                        'error_type':type(exc).__name__})
                    log_handled_failure('collections.streaming.local_identity',level='error',media_id=int(credit['id']))
                    media_rows.append({'tmdb_id':credit['id'],'title':credit['title'],'media_type':media_type,
                        'present':False,'library_item_ids':[],'sources':credit['sources'],
                        'ranks_by_source':credit['ranks_by_source'],'source_kinds':credit['source_kinds'],
                        'buzz_score':credit['buzz_score'],'arr_status':'identity_failed'})
                    continue
            if match_titles and matches:
                # The supplied Plex synchronizer publishes one local edition
                # for each ranked TMDb identity.
                matches=matches[:1]
            if fill_local_limit and not matches and len(missing_candidates) < config['limit']:
                missing_candidates.append({'title':credit['title'],'year':credit.get('year'),'tmdb_id':credit['id']})
            if matches and config['mode'] != 'arr' and config.get('required_audio_language'):
                try:
                    matches=[row for row in matches if get_adapter().has_audio(row,config['required_audio_language'])]
                except CollectionRunCancelled:raise
                except Exception as exc:
                    raise ValueError('collections.family_audio_unknown') from exc
                if not matches:continue  # Never acquire an unverifiable audio version.
                if config['limit']:
                    matches=matches[:max(0,config['limit']-len(selected))]
            # One remote title may match multiple local editions. Count actual
            # media IDs, not just discovery candidates, against the hard cap.
            matches=list({str(row['id']):row for row in matches}.values())
            if not matches and acquisition_ids is not None and credit['id'] not in acquisition_ids:
                # Lower ranks fill display slots using existing local titles;
                # they must not expand the configured top-N acquisition scope.
                continue
            if config['limit'] and matches:
                matches=[row for row in matches if str(row['id']) not in seen][:max(0,config['limit']-len(selected))]
                if not matches:continue
            for row in matches:
                if str(row['id']) not in seen:
                    selected.append(row); seen.add(str(row['id']))
            if not matches: missing.append(credit)
            media_rows.append({'tmdb_id':credit['id'],'title':credit['title'],'media_type':media_type,
                'present':bool(matches),'library_item_ids':[row['id'] for row in matches],
                'sources':credit['sources'],'ranks_by_source':credit['ranks_by_source'],
                'source_kinds':credit['source_kinds'],'buzz_score':credit['buzz_score'],
                'arr_status':'not_needed' if matches else 'not_requested' if config['arr_enabled'] else 'disabled'})
        selected=order_media(selected,config)
        result.update(present=len(selected),missing=len(missing))
        if fill_local_limit and len(selected)<config['limit']:
            result['warnings'].append('collections.limit_shortfall')
            result['diagnostics']['selection_shortfall']={
                'present':len(selected),'limit':config['limit'],
                'missing_candidates':missing_candidates[:config['limit']-len(selected)]}
        publication = {'person_key':object_key,'name':title,'collection_title':title,
                       'published':False,'media':media_rows,'selected':[row['title'] for row in selected]}
        result['people'].append(publication)
        obj = next((row for row in objects if row['person_key']==object_key),None)
        if config['mode']!='arr' and not preview:
            if not selected and partial:
                # No local matches in the successful subset is not evidence
                # that the old collection should be emptied or deleted.
                pass
            elif not selected and collection_settings(db)['suppress_empty']:
                if obj and obj['remote_id']: remove(obj)
            elif selected or obj and obj['remote_id']:
                if obj is None:
                    identifier = str(uuid.uuid4())
                    db.execute("INSERT INTO collection_objects(id,instance_id,person_key,title) VALUES(?,?,?,?)",
                        (identifier,instance['id'],object_key,title))
                    obj = dict(db.query_one('SELECT * FROM collection_objects WHERE id=?',(identifier,)))
                def created(remote_id):
                    db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,obj['id']))
                    heartbeat()
                progress('publish')
                same_region = instance['model'] not in ('streaming_country','streaming_worldwide') or obj['title'] in {streaming_title(instance['model'],language,config.get('country','FR'),config.get('region','worldwide'),config.get('content_language','')) for language in ('fr','en','de','es','it')}
                if instance['model'] in ('imdb','awards','top_country'): same_region = obj['title']==title
                warnings = get_adapter().sync(obj,title,selected,{**config,'collection_poster':poster_key_override or streaming_poster_key(instance['model'],config),'profile_path':getattr(source,'collection_profile_path',None),'summary':title+' · VODUM','preserve_existing':partial and same_region},created)
                result['warnings'].extend(warnings or [])
                db.execute("UPDATE collection_objects SET title=?,state='synced' WHERE id=?",(title,obj['id']))
                publication['published'] = True
        if missing and config['arr_enabled']:
            progress('acquisition')
            try:
                arr = CollectionArr(db,library,config,heartbeat=heartbeat)
            except CollectionRunCancelled: raise
            except Exception as exc:
                detail = failure_detail(exc,None,{'id':0,'title':library['name']},'preflight')
                result['warnings'].append('collections.arr_server_offline' if detail['reason']=='arr_server_offline' else 'collections.arr_blocked')
                log_arr_failure(instance,library,detail,exc)
                detail['severity'] = 'warning'
                result['arr_details'].append(detail)
                for row in media_rows:
                    if row['arr_status']=='not_requested': row['arr_status']='blocked'
                arr = None
            if arr:
                deadline, blocked = time.monotonic()+60, False
                for credit in missing:
                    row = next(row for row in media_rows if row['tmdb_id']==credit['id'])
                    if blocked or time.monotonic()>=deadline:
                        row['arr_status'] = 'blocked' if blocked else 'pending'
                        result['warnings'].append('collections.arr_pending')
                        continue
                    heartbeat()
                    stage = 'identity'
                    try:
                        external_id = credit['id'] if media_type=='movie' else source.media_external_ids('tv',credit['id']).get('tvdb_id')
                        if not external_id:
                            row['arr_status'] = 'no_tvdb'
                            result['warnings'].append('collections.arr_no_tvdb:'+str(credit['id']))
                            continue
                        stage = 'lookup'
                        status = arr.submit(instance['id'],external_id,preview=preview)
                        row['arr_status'] = status
                        result['arr_requests'] += int(status=='added')
                        result['arr_planned'] += int(status=='planned')
                        if status in ('pending','not_found','excluded'):
                            result['warnings'].append('collections.'+{'pending':'arr_pending','not_found':'arr_not_found','excluded':'arr_filtered'}[status])
                    except CollectionRunCancelled: raise
                    except Exception as exc:
                        row['arr_status'] = 'failed'
                        detail = failure_detail(exc,arr,credit,'identity' if stage=='identity' else getattr(arr,'stage','lookup'))
                        result['arr_details'].append(detail)
                        # Acquisition is optional and happens after publication.
                        # Retain the failed item/log detail without failing the
                        # successfully synchronized local collection.
                        result['warnings'].append('collections.arr_media_failed:'+str(credit['id']))
                        blocked = bool(getattr(exc,'connection_error',None) or detail['reason']=='arr_add_uncertain' or detail['http_status'] in (401,403,429,502,503,504))
                        log_arr_failure(instance,library,detail,exc)
        if 'selection_shortfall' in result['diagnostics']:
            acquisition_status = {row['tmdb_id']:row['arr_status'] for row in media_rows}
            for candidate in result['diagnostics']['selection_shortfall']['missing_candidates']:
                candidate['arr_status'] = acquisition_status.get(candidate['tmdb_id'], 'not_requested' if config['arr_enabled'] else 'disabled')
        result['outcome'] = 'preview' if preview else 'failed' if result['errors'] else 'published' if publication['published'] else 'empty'
        result['warnings'] = list(dict.fromkeys(result['warnings']))
        progress('complete')
        return result
    except (CollectionRunCancelled,CollectionOwnershipError) as exc:
        exc.result = result
        raise
    finally:
        if source is not None: source.close()
        if adapter is not None: adapter.close()


def run_streaming_worldwide(db, instance, **kwargs):
    return run_streaming_country(db,instance,**kwargs)
