from core.collections_ordering import order_media
"""One Memoria instance owns its detections, expiry dates and remote objects."""
import json
import os
import random
import uuid
import requests
import unicodedata
import time
from datetime import timedelta

from core.collections_arr import CollectionArr, failure_detail
from core.collections_people import prune_expired_people, person_rotation_key
from core.collections_media import media_adapter
from core.collection_inventory import CachedCollectionMedia
from core.collections_memoria_source import MemoriaSource
from core.collections_repository import stamp, utcnow, TRIBUTE_TITLES, CollectionRunCancelled, collection_settings
from core.error_reporting import log_handled_failure
from secret_store import decrypt_secret
from logging_utils import get_logger

TITLES = TRIBUTE_TITLES


def run_memoria(db, instance, *, kind='sync', heartbeat=lambda:None, source_factory=MemoriaSource, adapter_factory=media_adapter):
    now = utcnow()
    config = json.loads(instance['config_json'])
    config['_order_seed']=uuid.uuid4().hex
    preview = kind == 'preview'
    suppress_empty = collection_settings(db)['suppress_empty']
    cleanup_only = kind in ('cleanup','delete')
    library = dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server = dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    result = {'people':[], 'present':0, 'missing':0, 'arr_requests':0, 'arr_planned':0,
              'warnings':[], 'errors':[], 'arr_details':[], 'deleted':0, 'preview':preview}
    started = time.monotonic()
    def progress(stage, **counts):
        result['stage'] = stage
        get_logger('collections').info(
            'Memoria instance=%s stage=%s elapsed=%.1fs counts=%s',
            instance['id'], stage, time.monotonic()-started, counts)
        reporter = getattr(heartbeat,'report',None)
        if callable(reporter): reporter(result)
        heartbeat()
    adapter = source = None
    objects = [dict(row) for row in db.query('SELECT * FROM collection_objects WHERE instance_id=?',(instance['id'],))]
    choices = {row['tmdb_id']:dict(row) for row in db.query('SELECT * FROM collection_person_choices WHERE group_id=?',(instance.get('group_id') or instance['id'],))}
    excluded_ids = {key for key,row in choices.items() if row['excluded']}
    people = {row['person_key']:dict(row) for row in db.query('SELECT * FROM collection_people WHERE instance_id=?',(instance['id'],))}
    def get_adapter():
        nonlocal adapter
        if adapter is None:
            adapter = CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
            adapter.heartbeat = heartbeat
        return adapter
    try:
        # Expiry is independent of source/API availability and of enabled state.
        for obj in objects:
            person = people.get(obj['person_key'])
            remove = cleanup_only or config['mode']=='arr' or person and (person['expires_at'] <= stamp(now) or person['tmdb_id'] in excluded_ids)
            if not remove or obj['state']=='deleted':
                continue
            heartbeat()
            if not preview:
                if obj['remote_id']:
                    get_adapter().delete(obj)
                db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(obj['id'],))
            obj.update(state='deleted',remote_id=None)
            result['deleted'] += 1
        if not preview:
            prune_expired_people(db,instance,config['detection_days'])
        if cleanup_only or kind=='expire':
            return result

        shared = db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key = decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        source = source_factory(key,config['language'])
        if isinstance(source,MemoriaSource):
            source.db = db
        source.heartbeat = heartbeat
        progress('discovery')
        try:
            candidates = source.recent_deaths(now,config['detection_days'],config['credits'])
        except requests.RequestException:
            # An unavailable discovery service must not block maintenance of
            # previously verified, unexpired tributes. Never invent new deaths.
            if not any(person['expires_at']>stamp(now) for person in people.values()):
                raise
            log_handled_failure('collections.memoria.discovery')
            result['warnings'].append('collections.discovery_unavailable')
            candidates = []
        # Known events retain their original first detection / expiry forever.
        # Refresh surviving people even when they fall outside the detection window.
        candidates_by_key = {row['person_key']:row for row in candidates}
        for person in people.values():
            if person['expires_at'] > stamp(now):
                candidates_by_key.setdefault(person['person_key'],json.loads(person['data_json']))
        for choice in choices.values():
            if choice['manual'] and not choice['excluded'] and choice['expires_at']>stamp(now):
                candidate = {**json.loads(choice['data_json']),'manual':True}
                candidates_by_key[candidate['person_key']] = candidate
        by_id = {}
        suppressed = [dict(row) for row in db.query('SELECT * FROM collection_person_tombstones WHERE instance_id=? AND suppress_until>?',(instance['id'],stamp(now)))]
        suppressed_ids = {row['tmdb_id'] for row in suppressed}
        suppressed_keys = {row['person_key'] for row in suppressed}
        result['filtered_people'] = 0
        for candidate in candidates_by_key.values():
            tmdb_id = candidate.get('tmdb_id')
            if tmdb_id in excluded_ids:
                continue
            if not candidate.get('manual'):
                if tmdb_id in suppressed_ids or candidate['person_key'] in suppressed_keys:
                    continue
                cached = people.get(candidate['person_key'])
                if not preview and cached and 'popularity_score' in candidate and (not tmdb_id or cached['tmdb_id']==tmdb_id):
                    metadata = json.loads(cached['data_json'])
                    metadata['popularity_score'] = int(candidate.get('popularity_score') or 0)
                    db.execute('UPDATE collection_people SET data_json=? WHERE instance_id=? AND person_key=?',
                        (json.dumps(metadata),instance['id'],cached['person_key']))
                if int(candidate.get('popularity_score') or 0)<config.get('min_popularity',25):
                    result['filtered_people'] += 1
                    continue
            # Coalesce manual and automatic discoveries of the same TMDb person.
            dedup_key = str(tmdb_id) if tmdb_id else candidate['person_key']
            if dedup_key not in by_id or candidate.get('manual'):
                by_id[dedup_key] = candidate
        progress('verify_people', candidates=len(by_id))
        verified, protected_ids = [], set()
        for candidate in by_id.values():
            heartbeat()
            try:
                person = source.manual_person(candidate['tmdb_id']) if candidate.get('manual') else source.verify_person(candidate)
                if person is not None:
                    person['manual'] = bool(candidate.get('manual'))
                    if person['tmdb_id'] in excluded_ids:
                        continue
                if person is None:
                    if candidate.get('tmdb_id'):
                        protected_ids.add(candidate['tmdb_id'])
                    if candidate['person_key'] in people:
                        protected_ids.add(people[candidate['person_key']]['tmdb_id'])
                    result['warnings'].append('collections.person_unverified:' + candidate['person_key'])
                    continue
                event = people.get(person['person_key'])
                if event and event['tmdb_id']!=person['tmdb_id']:
                    raise RuntimeError('Conflicting stable person identity')
                if event is None:
                    event = next((row for row in people.values() if row['tmdb_id']==person['tmdb_id']),None)
                if event:
                    person['person_key'] = event['person_key']
                if person.get('popularity_score') is None:
                    # A temporary Wikidata failure is not evidence of score 0.
                    previous_score=(json.loads(event['data_json']).get('popularity_score')
                        if event and event.get('data_json') else None)
                    if previous_score is None:
                        previous_score=candidate.get('popularity_score')
                    person['popularity_score']=previous_score
                choice = choices.get(person['tmdb_id'])
                manual = bool(candidate.get('manual') and choice)
                if event and event['expires_at'] <= stamp(now) and not manual:
                    continue
                if event and event['tmdb_id'] != person['tmdb_id']:
                    raise RuntimeError('Conflicting stable person identity')
                detected = event['detected_at'] if event else stamp(now)
                expiry = choice['expires_at'] if manual else event['expires_at'] if event else stamp(now+timedelta(days=config['retention']))
                if manual:
                    detected = choice['added_at']
                if not preview:
                    db.execute("""INSERT INTO collection_people(instance_id,person_key,tmdb_id,name,death_date,detected_at,expires_at,data_json)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(instance_id,person_key) DO UPDATE
                        SET name=excluded.name,data_json=excluded.data_json,detected_at=excluded.detected_at,expires_at=excluded.expires_at""",
                        (instance['id'],person['person_key'],person['tmdb_id'],person['name'],person['death_date'],detected,expiry,json.dumps(person)))
                person['detected_at'] = detected
                people[person['person_key']] = {**(event or {}),**person,'expires_at':expiry}
                verified.append((person,expiry))
            except CollectionRunCancelled:
                raise
            except Exception:
                if candidate.get('tmdb_id'):
                    protected_ids.add(candidate['tmdb_id'])
                if candidate['person_key'] in people:
                    protected_ids.add(people[candidate['person_key']]['tmdb_id'])
                log_handled_failure('collections.memoria.verify_person')
                result['errors'].append('collections.person_failed:' + candidate['person_key'])

        maximum = config.get('max_people',4)
        published_ids = {people[obj['person_key']]['tmdb_id'] for obj in objects if obj['remote_id'] and obj['state']!='deleted' and obj['person_key'] in people}
        protected_ids = set(sorted(protected_ids & published_ids)[:maximum])
        verified.sort(key=lambda item:person_rotation_key(item[0]),reverse=True)
        selected_people = verified[:max(0,maximum-len(protected_ids))]
        allowed = protected_ids | {person['tmdb_id'] for person,expiry in selected_people}
        result['waiting_people'] = max(0,len(verified)-len(selected_people))
        def published_objects():
            return [obj for obj in objects if obj['state']!='deleted' and obj['remote_id']]

        def remove_lowest_score():
            eligible = [obj for obj in published_objects()
                        if people.get(obj['person_key'],{}).get('tmdb_id') not in protected_ids]
            if not eligible:raise ValueError('collections.publication_failed')
            obj = min(eligible,key=lambda obj:(
                people.get(obj['person_key'],{}).get('tmdb_id') in allowed,
                person_rotation_key(people[obj['person_key']]),obj['person_key']))
            heartbeat()
            if not preview:
                get_adapter().delete(obj)
                db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(obj['id'],))
            obj.update(state='deleted',remote_id=None)
            result['deleted'] += 1

        # A lower cap applies immediately. Replacement, however, waits until
        # the newcomer has local media: an empty filmography must not evict an
        # existing tribute just because a new death was detected.
        while len(published_objects())>maximum:
            remove_lowest_score()
        if not selected_people:
            return result
        progress('inventory', people=len(selected_people))
        inventory = get_adapter().inventory()
        progress('match', media=len(inventory))
        def normalized(value):
            value = ''.join(char for char in unicodedata.normalize('NFKD',str(value or '').casefold()) if not unicodedata.combining(char))
            return ' '.join(''.join(char if char.isalnum() else ' ' for char in value).split())
        by_title_year = {}
        for media in inventory:
            for title in {normalized(media.get('title')),normalized(media.get('original_title'))} - {''}:
                by_title_year.setdefault((str(media.get('year') or ''),title),[]).append(media)
        by_tmdb = {}
        alternate_ids = {'imdb':{},'tvdb':{}}
        for media in inventory:
            if media.get('tmdb'):
                by_tmdb.setdefault(str(media['tmdb']),[]).append(media)
            for provider in alternate_ids:
                if media.get(provider) and not media.get('tmdb'):
                    alternate_ids[provider].setdefault(str(media[provider]),[]).append(media)
        media_type = 'movie' if library['type'] in ('movie','movies','film','films') else 'tv'
        arr = None
        arr_unavailable = False
        arr_jobs = []
        for person,expiry in selected_people:
            heartbeat()
            # Do not publish past expiry even if discovery/downloads took a long time.
            if stamp() >= expiry:
                continue
            credits = source.eligible_credits(person,media_type,config['credits'])
            if config['sort']=='popularity':
                credits.sort(key=lambda row:float(row.get('popularity') or 0),reverse=True)
            matches, missing = [], []
            media_rows = []
            identity_uncertain = False
            for credit in credits:
                found = list(by_tmdb.get(str(credit['id']),[]))
                # Exhaust exact local title/year matches before resolving remote
                # alternate IDs. One legacy entry must not force a TMDb request
                # for every already identifiable film in the library.
                if not found:
                    year = str(credit.get('release_date') or credit.get('first_air_date') or '')[:4]
                    if year:
                        for key in ('title','name','original_title','original_name'):
                            found.extend(row for row in by_title_year.get((year,normalized(credit.get(key))),[])
                                         if not row.get('tmdb') or str(row['tmdb'])==str(credit['id']))
                if not found and any(alternate_ids.values()):
                    heartbeat()
                    try:
                        external = source.media_external_ids(media_type,credit['id'])
                        for provider,index in alternate_ids.items():
                            found.extend(index.get(str(external.get(provider+'_id') or ''),[]))
                    except CollectionRunCancelled:
                        raise
                    except Exception as exc:
                        if isinstance(exc,requests.HTTPError) and exc.response is not None and exc.response.status_code==404:
                            result['warnings'].append('collections.media_unavailable:'+str(credit['id']))
                            media_rows.append({'tmdb_id':credit['id'],'title':credit.get('title') or credit.get('name') or str(credit['id']),
                                'media_type':media_type,'present':False,'arr_status':'identity_failed'})
                            continue
                        # An unknown identity must not be treated as an absent
                        # title and sent to ARR; keep this person unchanged.
                        log_handled_failure('collections.memoria.media_identity')
                        result['errors'].append('collections.media_identity_failed:'+str(credit['id']))
                        identity_uncertain = True
                        found = None
                media_rows.append({'tmdb_id':credit['id'],'title':credit.get('title') or credit.get('name') or str(credit['id']),
                    'media_type':media_type,'present':bool(found),'library_item_ids':[row['id'] for row in found or []],
                    'arr_status':'identity_failed' if found is None else 'not_needed' if found else 'disabled' if not config['arr_enabled'] else 'not_requested'})
                if found is None:
                    continue
                if found:
                    matches.extend(found)
                else:
                    missing.append(credit)
            # Memoria also consults the library's person credits, which can
            # contain films absent from today's TMDb filmography.
            person_lookup = getattr(get_adapter(),'complete_person_items',None) or getattr(get_adapter(),'person_items',None)
            if callable(person_lookup):
                try:
                    local = person_lookup(person,config['credits'])
                    inventory_by_id = {row['id']:row for row in inventory}
                    matches.extend({**inventory_by_id.get(row['id'],{}),**row} for row in local)
                except CollectionRunCancelled:
                    raise
                except Exception:
                    log_handled_failure('collections.memoria.person_items')
                    result['warnings'].append('collections.person_items_failed')
            for credit in missing[:]:
                year = str(credit.get('release_date') or credit.get('first_air_date') or '')[:4]
                titles = {normalized(credit.get(key)) for key in ('title','name','original_title','original_name')} - {''}
                title_matches = [row for title in titles for row in by_title_year.get((year,title),[])
                                 if not row.get('tmdb') or str(row['tmdb'])==str(credit['id'])] if year else []
                title_matches.extend(row for row in matches if str(row.get('tmdb') or '')==str(credit['id']))
                if title_matches:
                    matches.extend(title_matches)
                    missing.remove(credit)
                    next(row for row in media_rows if row.get('tmdb_id')==credit['id']).update(
                        present=True,arr_status='not_needed',library_item_ids=[row['id'] for row in title_matches])
            matches = list({row['id']:row for row in matches}.values())
            for media_row in media_rows:
                if any(str(row.get('tmdb') or '')==str(media_row['tmdb_id']) for row in matches):
                    media_row.update(present=True,arr_status='not_needed')
            listed_items = {identifier for row in media_rows for identifier in row.get('library_item_ids',[])}
            for row in matches:
                if row['id'] not in listed_items and not any(str(row.get('tmdb') or '')==str(media.get('tmdb_id')) for media in media_rows):
                    media_rows.append({'title':row['title'],'media_type':media_type,'present':True,
                                       'library_item_ids':[row['id']],'arr_status':'not_needed'})

            if config['sort']=='daily_random':
                random.shuffle(matches)
            selected = matches[:config['limit']] if config['limit'] else matches
            selected=order_media(selected,config)
            result['present'] += len(matches)
            result['missing'] += len(missing)
            person_result = {'person_key':person['person_key'], 'name':person['name'], 'expires_at':expiry,
                             'popularity_score':int(person.get('popularity_score') or 0),'profile_path':person.get('profile_path'),
                             'validated':bool(person.get('manual')),'published':False,
                             'collection_title':TITLES[config['language']].format(name=person['name']),'media':media_rows,
                             'present':len(matches), 'missing':len(missing), 'selected':[row['title'] for row in selected]}
            result['people'].append(person_result)
            if suppress_empty and not matches and not identity_uncertain and not preview and config['mode']!='arr':
                old = db.query_one('SELECT * FROM collection_objects WHERE instance_id=? AND person_key=?',
                    (instance['id'],person['person_key']))
                if old and old['remote_id']:
                    try:
                        get_adapter().delete(dict(old))
                        db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(old['id'],))
                    except CollectionRunCancelled:
                        raise
                    except Exception:
                        log_handled_failure('collections.memoria.remove_empty')
                        result['errors'].append('collections.publication_failed:'+person['person_key'])
            retained_empty = not suppress_empty and not matches and db.query_one('SELECT remote_id FROM collection_objects WHERE instance_id=? AND person_key=? AND remote_id IS NOT NULL',(instance['id'],person['person_key']))
            if config['mode']!='arr' and (matches or retained_empty) and not preview and stamp()<expiry:
                try:
                    if not any(obj['person_key']==person['person_key'] for obj in published_objects()):
                        while len(published_objects())>=maximum:
                            remove_lowest_score()
                    title = TITLES[config['language']].format(name=person['name'])
                    with db.transaction() as cur:
                        cur.execute("""INSERT INTO collection_objects(id,instance_id,person_key,title)
                            VALUES(?,?,?,?) ON CONFLICT(instance_id,person_key) DO NOTHING""",
                            (str(uuid.uuid4()),instance['id'],person['person_key'],title))
                        obj = dict(cur.execute('SELECT * FROM collection_objects WHERE instance_id=? AND person_key=?',
                            (instance['id'],person['person_key'])).fetchone())
                    def record_created(remote_id):
                        # Save a successful remote creation even if the deadline
                        # or stop request arrived while its POST was in flight.
                        db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,obj['id']))
                        obj.update(remote_id=remote_id,state='created')
                        existing = next((item for item in objects if item['id']==obj['id']),None)
                        if existing is None:objects.append(obj)
                        else:existing.update(obj)
                        heartbeat()
                    progress('publish', person=person['tmdb_id'], selected=len(selected))
                    settings = {**config,'profile_path':person.get('profile_path'),'collection_poster':'memoria','preserve_existing':identity_uncertain,'summary':title+' · '+person['death_date']+' · VODUM Memoria'}
                    warnings = get_adapter().sync(obj,title,selected,settings,record_created)
                    person_result['published'] = True
                    db.execute("UPDATE collection_objects SET state='synced',title=? WHERE id=?",(title,obj['id']))
                    result['warnings'].extend(warnings)
                except CollectionRunCancelled:
                    raise
                except Exception as exc:
                    log_handled_failure('collections.memoria.publish')
                    code = str(exc) if str(exc) in ('collections.ownership_failed','collections.title_collision','collections.publication_failed') else 'collections.publication_failed'
                    result['errors'].append(code + ':' + person['person_key'])
                    if code in ('collections.ownership_failed','collections.title_collision'):
                        # Acquisitions cannot repair a publication ownership conflict.
                        for media_row in media_rows:
                            if media_row['arr_status']=='not_requested':
                                media_row['arr_status']='blocked'
                        continue
            if config['arr_enabled'] and missing:
                arr_jobs.append((missing,media_rows,expiry))
        if arr_jobs:
            try:
                arr = CollectionArr(db,library,config,heartbeat=heartbeat)
            except CollectionRunCancelled:
                raise
            except Exception as exc:
                log_handled_failure('collections.memoria.arr_preflight')
                result['warnings'].append('collections.arr_blocked')
                detail = failure_detail(exc,None,{'id':0,'title':library.get('name','')},'preflight')
                detail['severity'] = 'warning'
                result['arr_details'].append(detail)
                if str(exc) in ('collections.arr_route_required','collections.arr_defaults_required'):
                    result['warnings'].append(str(exc))
        if arr is None:
            for _,rows,_ in arr_jobs:
                for row in rows:
                    if row['arr_status']=='not_requested': row['arr_status']='blocked'
        if arr is not None and arr_jobs:
            progress('acquisition', people=len(arr_jobs))
            acquisition_deadline = time.monotonic() + 60
            for missing,media_rows,expiry in arr_jobs:
                for credit in missing:
                    media_row = next(row for row in media_rows if row['tmdb_id']==credit['id'])
                    if time.monotonic() >= acquisition_deadline:
                        media_row['arr_status'] = 'pending'
                        result['warnings'].append('collections.arr_pending:'+str(credit['id']))
                        continue
                    if arr_unavailable:
                        media_row['arr_status'] = 'blocked'
                        continue
                    heartbeat()
                    if stamp() >= expiry:
                        break
                    try:
                        stage = 'identity'
                        external_id = credit['id']
                        if media_type=='tv':
                            external_id = source.media_external_ids('tv',credit['id']).get('tvdb_id')
                            if not external_id:
                                media_row['arr_status'] = 'no_tvdb'
                                result['warnings'].append('collections.arr_no_tvdb:'+str(credit['id']))
                                result['arr_details'].append({'tmdb_id':credit['id'],'title':credit.get('name') or credit.get('title') or str(credit['id']),
                                    'stage':'identity','reason':'arr_no_tvdb','severity':'warning'})
                                continue
                        stage = 'lookup'
                        status = arr.submit(instance['id'],external_id,preview=preview)
                        media_row['arr_status'] = status
                        result['arr_requests'] += int(status=='added')
                        result['arr_planned'] += int(status=='planned')
                        if status=='excluded':
                            result['warnings'].append('collections.arr_filtered')
                        elif status in ('not_found','pending'):
                            reason = 'arr_not_found' if status=='not_found' else 'arr_pending'
                            result['warnings'].append('collections.'+reason+':'+str(credit['id']))
                            result['arr_details'].append({'tmdb_id':credit['id'],'title':credit.get('title') or credit.get('name') or str(credit['id']),
                                'stage':'lookup','reason':reason,'severity':'warning'})
                    except CollectionRunCancelled:
                        raise
                    except Exception as exc:
                        media_row['arr_status'] = 'failed'
                        log_handled_failure('collections.memoria.arr_media')
                        detail = failure_detail(exc,arr,credit,'identity' if stage=='identity' else getattr(arr,'stage','lookup'))
                        result['arr_details'].append(detail)
                        get_logger('collections').error('ARR media failed details=%s',json.dumps(detail,ensure_ascii=False))
                        result['warnings'].append('collections.arr_media_failed:' + str(credit['id']))
                        if getattr(exc,'connection_error',None) or detail['reason']=='arr_add_uncertain' or detail['http_status'] in (401,403,429,502,503,504):
                            arr_unavailable = True
        result['warnings'] = list(dict.fromkeys(result['warnings']))
        arr_errors = [detail for detail in result['arr_details'] if detail['severity']=='error']
        if arr_errors:
            result['retryable'] = any(detail['retryable'] for detail in arr_errors)
        progress('complete', present=result['present'], missing=result['missing'])
        return result
    except CollectionRunCancelled as exc:
        exc.result = result
        raise
    finally:
        if source is not None:
            source.close()
        if adapter is not None:
            adapter.close()
