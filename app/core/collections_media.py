from core.collections_ordering import order_media, stationary_members
from core.collections_limits import bounded_members, removable_member_ids
from core.collections_posters import collection_poster, plex_has_custom_poster, object_poster_key
from core.collections_visibility import collection_visibility, collection_sort_title, priority_config
"""Collection operations scoped by library and verified VODUM ownership.

Never look up or adopt a collection by its display title. Titles are checked
only for collisions. Only IDs returned by our own create call are recorded.
"""
from urllib.parse import quote, urlencode
import base64
import hashlib
import json
import re
import time
import requests
import threading
from weakref import WeakValueDictionary
from core.collections_portraits import portrait_path, fetch_portrait
from core.error_reporting import log_handled_failure
from core.collections_repository import CollectionRunCancelled

from logging_utils import get_logger
from plexapi.exceptions import NotFound, BadRequest
from plexapi.collection import Collection as PlexCollection
from core.http_security import server_http_session
from core.jellyfin_auth import jellyfin_headers
from core.plex_connection import get_plex_server

_visibility_locks=WeakValueDictionary()
_visibility_lock_guard=threading.Lock()


def artwork_changed(adapter,record,remote_id,path):
    db=vars(adapter).get('collection_db')
    if db is None:
        saved=vars(adapter).get('_artwork_versions',{}).get(record['id'])
        return saved is not None and saved!=(str(remote_id),hashlib.sha256(path.read_bytes()).hexdigest())
    saved=db.query_one('SELECT remote_id,digest FROM collection_object_artwork WHERE object_id=?',(record['id'],))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    return saved is None or saved['remote_id']!=str(remote_id) or saved['digest']!=digest


def remember_artwork(adapter,record,remote_id,path):
    db=vars(adapter).get('collection_db')
    if db is None:
        adapter.__dict__.setdefault('_artwork_versions',{})[record['id']]=(str(remote_id),hashlib.sha256(path.read_bytes()).hexdigest())
        return
    if db is not None:
        db.execute('INSERT OR REPLACE INTO collection_object_artwork(object_id,remote_id,digest) VALUES(?,?,?)',
            (record['id'],str(remote_id),hashlib.sha256(path.read_bytes()).hexdigest()))


def visibility_lock(record):
    # Only serialize the short presentation step, never a whole population.
    # A control command and a slow sync must not overwrite each other's Home
    # destinations with a configuration read before the other command finished.
    key=str(record.get('id') or record.get('remote_id') or '')
    with _visibility_lock_guard:
        lock=_visibility_locks.get(key)
        if lock is None:
            lock=threading.RLock();_visibility_locks[key]=lock
        return lock


def audio_language(value, expected):
    code = str(value or '').strip().lower().replace('_','-').split('-')[0].split('(')[0].strip()
    aliases = {'fr':{'fr','fra','fre','french','français','francais','french canadian','francais canadien','français canadien'},
               'en':{'en','eng','english'},'de':{'de','deu','ger','german'},
               'es':{'es','spa','spanish'},'it':{'it','ita','italian'}}
    iso3=dict(pair.split(':') for pair in 'pt:por ar:ara hi:hin ta:tam te:tel ml:mal kn:kan bn:ben mr:mar pa:pan gu:guj ur:urd ja:jpn ko:kor zh:zho id:ind th:tha vi:vie tl:tgl ms:msa tr:tur fa:fas he:heb ru:rus uk:ukr pl:pol nl:nld sv:swe da:dan no:nor fi:fin cs:ces hu:hun ro:ron el:ell sw:swa af:afr'.split())
    return code in aliases.get(expected,{expected,iso3.get(expected,expected)})


def plex_snapshot_ids(item):
    """Read lazy GUIDs from the XML already returned, without a metadata reload."""
    fields = vars(item)
    data = fields.get('_data')
    raw_ids = [str(g.id) for g in (fields.get('guids') or [])]
    if data is not None:
        raw_ids.extend(node.get('id','') for node in data.findall('Guid'))
    raw_ids.append(str(fields.get('guid') or ''))
    providers = {}
    for raw in raw_ids:
        if '://' not in raw:
            continue
        provider,value = raw.split('://',1)
        provider = {'com.plexapp.agents.imdb':'imdb','com.plexapp.agents.themoviedb':'tmdb',
                    'com.plexapp.agents.thetvdb':'tvdb'}.get(provider.lower(),provider.lower())
        value = value.split('?',1)[0].strip('/')
        if provider in ('tmdb','tvdb'):
            if not value.isdigit() or int(value)<=0:
                continue
            value = str(int(value))
        if provider in ('tmdb','imdb','tvdb') and value:
            providers.setdefault(provider,set()).add(value)
    return {provider:next(iter(values)) for provider,values in providers.items() if len(values)==1}


class CollectionOwnershipError(RuntimeError):
    def __init__(self,code,*,conflict=None):
        super().__init__(code)
        self.conflict=conflict or {}



def plex_has_collection_marker(obj, marker):
    # Plex can capitalize the first letter of a label when storing it. Compare
    # the full UUID marker case-insensitively; never match only a prefix/title.
    return marker.casefold() in {str(label.tag).casefold() for label in (obj.labels or [])}


class PlexCollections:
    supports_order = True
    publication_budget_seconds = 120

    def __init__(self, server, library):
        self.plex = get_plex_server(server)
        self.heartbeat = lambda: None
        original_request = self.plex._session.request
        def request(*args, **kwargs):
            self.heartbeat()
            metrics=getattr(self.heartbeat,'metrics',None)
            if isinstance(metrics,dict):
                method=str(args[0] if args else kwargs.get('method','GET')).upper()
                key='reads' if method in ('GET','HEAD') else 'writes'
                metrics[key]=metrics.get(key,0)+1
            started=time.perf_counter()
            try:return original_request(*args, **kwargs)
            finally:
                if isinstance(metrics,dict):metrics['remote_seconds']=round(metrics.get('remote_seconds',0)+time.perf_counter()-started,4)
        self.plex._session.request = request
        self.plex._session._vodum_before_request = lambda:self.heartbeat()
        self.plex._session._vodum_request_priority = lambda:getattr(self.heartbeat,'priority',False) is True
        def on_wait(seconds):
            metrics=getattr(self.heartbeat,'metrics',None)
            if isinstance(metrics,dict):metrics['rate_wait_seconds']=round(metrics.get('rate_wait_seconds',0)+seconds,4)
        self.plex._session._vodum_on_wait=on_wait
        self.section = self.plex.library.sectionByID(int(library['section_id']))
        self.section_id = str(library['section_id'])

    def close(self):
        self.plex._session.close()

    def inventory(self):
        # PlexAPI paginates this scan. Do it once per instance, not per person.
        result = []
        items = self.section.all(includeGuids=1,container_size=1000)
        expected = getattr(items,'totalSize',None)
        if isinstance(expected,int) and expected!=len(items):
            raise ValueError('collections.inventory_invalid')
        for item in items:
            fields = vars(item)
            ids = plex_snapshot_ids(item)
            result.append({'id':str(item.ratingKey), **ids, 'item':item, 'title':item.title, 'original_title':fields.get('originalTitle'), 'year':fields.get('year'),
                           'rating':fields.get('audienceRating') or fields.get('rating'), 'added_at':fields.get('addedAt'), 'release_date':fields.get('originallyAvailableAt'),
                           'countries':[node.get('tag','') for node in fields['_data'].findall('Country')] if fields.get('_data') is not None else [],
                           'genres':[node.get('tag','') for node in fields['_data'].findall('Genre')] if fields.get('_data') is not None else [],
                           'labels':[node.get('tag','') for node in fields['_data'].findall('Label')] if fields.get('_data') is not None else [],'summary':fields.get('summary'),
                           'people':{'actors':[node.get('tag','') for node in fields['_data'].findall('Role')] if fields.get('_data') is not None else [],
                                     'directors':[node.get('tag','') for node in fields['_data'].findall('Director')] if fields.get('_data') is not None else []}})
        return result

    def collection_members(self, record):
        obj = self._owned(record)
        if obj is None:
            return []
        rows = []
        for item in obj.items():
            fields = vars(item)
            ids = plex_snapshot_ids(item)
            rows.append({'id':str(item.ratingKey),'title':item.title,'item':item,
                         'rating':fields.get('audienceRating') or fields.get('rating'), 'added_at':fields.get('addedAt'), 'release_date':fields.get('originallyAvailableAt'),
                         'tmdb':ids.get('tmdb')})
        return rows

    def has_audio(self, row, language):
        self.heartbeat()
        item = row['item']
        item.reload()
        if getattr(item,'type',None)=='show':
            episodes=item.episodes()
            return bool(episodes) and all(self.has_audio({'item':episode},language) for episode in episodes)
        return any(media.parts and all(any(any(audio_language(getattr(stream,key,None),language)
            for key in ('languageCode','languageTag','language')) for stream in part.audioStreams())
            for part in media.parts) for media in item.media)

    def person_items(self, person, credits):
        results = {}
        names = {name.strip().casefold() for name in [person['name'],*(person.get('aliases') or [])] if name.strip()}
        filters = ['actor'] if credits=='actors' else ['director'] if credits=='directors' else ['actor','director']
        if not hasattr(self,'_person_choices'):
            self._person_choices = {}
        for role in filters:
            if role not in self._person_choices:
                self.heartbeat()
                self._person_choices[role] = self.section.listFilterChoices(role)
            choices = [choice for choice in self._person_choices[role] if choice.title.strip().casefold() in names]
            if not choices:
                continue
            self.heartbeat()
            # Passing FilterChoice objects avoids PlexAPI downloading the entire
            # actor index again for every name/alias in every person's query.
            for item in self.section.search(**{role:choices}):
                results[str(item.ratingKey)] = {'id':str(item.ratingKey),'item':item,'title':item.title,
                    **plex_snapshot_ids(item),'year':vars(item).get('year'),'original_title':vars(item).get('originalTitle')}
        return list(results.values())

    def _owned(self, record):
        if not record['remote_id']:
            return None
        try:
            obj = self.plex.fetchItem(int(record['remote_id']))
        except NotFound:
            return None
        marker = 'vodum:collection:' + record['id']
        # Some Plex metadata responses omit the library section. Resolve that
        # scope through the library's own collection inventory, never a title.
        section_id = getattr(obj,'librarySectionID',None)
        if section_id is None:
            scoped = next((item for item in self.section.collections()
                           if str(item.ratingKey)==str(record['remote_id'])),None)
            if scoped is None:
                raise CollectionOwnershipError('collections.ownership_failed')
            # Keep the full metadata object: scoped inventory entries may omit labels.
            section_id = self.section_id
        if not plex_has_collection_marker(obj, marker):
            # A partial response can omit Label elements. Reload the stored ID
            # once before rejecting it; never infer ownership from its title.
            obj.reload()
        pending = record.get('state')=='created' and obj.title in (
            'VODUM '+record['id'],record.get('title'))
        if (getattr(obj,'type',None) != 'collection' or str(section_id) != self.section_id
                or not pending and not plex_has_collection_marker(obj, marker)):
            get_logger('collections').error(
                'Plex collection ownership rejected | collection_id=%s | type_valid=%s | library_valid=%s | marker_present=%s',
                int(record['remote_id']),getattr(obj,'type',None)=='collection',
                str(section_id)==self.section_id,plex_has_collection_marker(obj, marker))
            raise CollectionOwnershipError('collections.ownership_failed')
        if pending and not record.get('read_only') and not plex_has_collection_marker(obj, marker):
            self._mark_created(obj, record)
        return obj

    def _mark_created(self, obj, record):
        """Confirm the ownership marker before any further publication work."""
        marker = 'vodum:collection:' + record['id']
        obj.addLabel(marker)
        # Plex can acknowledge the edit before its metadata read reflects it.
        # Bounded reads recover that lag without weakening the ownership check.
        for _ in range(3):
            obj.reload()
            if plex_has_collection_marker(obj, marker):return
        if not plex_has_collection_marker(obj, marker):
            get_logger('collections').error(
                'Plex collection marker not confirmed after creation | collection_id=%s',
                int(obj.ratingKey))
            raise CollectionOwnershipError('collections.ownership_failed')

    def _rename_owned(self, obj, record, title):
        """Retry a rejected edit from fresh, ownership-checked Plex metadata.

        A rejected response must not cause another collection to be created.
        Plex may already have applied the edit, so read before retrying it.
        """
        try:
            obj.editTitle(title)
        except BadRequest:
            self.heartbeat()
            fresh=self._owned({**record,'remote_id':str(obj.ratingKey)})
            if fresh is None:
                raise RuntimeError('collections.publication_failed')
            if fresh.title!=title:
                try:
                    fresh.editTitle(title)
                except BadRequest:
                    log_handled_failure('collections.plex.rename',level='error',
                                        collection_id=int(obj.ratingKey))
                    raise ValueError('collections.plex_title_rejected') from None
            fresh.reload()
            if fresh.title!=title:
                raise RuntimeError('collections.publication_failed')
            obj.title=title

    def _track_replacement(self, record, remote_id):
        db=vars(self).get('collection_db')
        if db is not None:
            db.execute('INSERT OR IGNORE INTO collection_replaced_objects(object_id,remote_id) VALUES(?,?)',
                (record['id'],str(remote_id)))

    def _cleanup_replacements(self, record, current):
        db=vars(self).get('collection_db')
        if db is None:return
        for row in db.query('SELECT remote_id FROM collection_replaced_objects WHERE object_id=?',(record['id'],)):
            if row['remote_id']==str(current.ratingKey if current is not None else record.get('remote_id')):continue
            self.heartbeat()
            old=self._owned({**record,'remote_id':row['remote_id'],'state':'synced','read_only':True})
            if old is not None:old.delete()
            db.execute('DELETE FROM collection_replaced_objects WHERE object_id=? AND remote_id=?',
                (record['id'],row['remote_id']))

    def _inventory_generation(self):
        db=vars(self).get('collection_db');library_id=vars(self).get('collection_library_id')
        if db is None or library_id is None:return None
        row=db.query_one('SELECT generation FROM collection_inventory WHERE library_id=?',(library_id,))
        return row['generation'] if row else None

    def _unavailable_media(self):
        generation=self._inventory_generation()
        if not generation:return set(vars(self).get('_missing_media',set()))
        return {row['media_id'] for row in self.collection_db.query(
            'SELECT media_id FROM collection_unavailable_media WHERE library_id=? AND generation=?',
            (self.collection_library_id,generation))}

    def _confirm_missing_media(self, item):
        """Only a verified 404 excludes an item; other failures remain retryable."""
        if vars(self).get('plex') is None:return False
        self.heartbeat()
        try:self.plex.fetchItem(int(item.ratingKey))
        except NotFound:
            media_id=str(item.ratingKey)
            generation=self._inventory_generation()
            if generation:
                self.collection_db.execute('INSERT OR IGNORE INTO collection_unavailable_media VALUES(?,?,?)',
                    (self.collection_library_id,generation,media_id))
            else:self.__dict__.setdefault('_missing_media',set()).add(media_id)
            return True
        return False

    def sync(self, record, title, matches, config, record_created):
        config=priority_config(vars(self).get('collection_db'),record,config)
        self.publication_changes=0
        unavailable=self._unavailable_media()
        skipped=unavailable & {str(row['id']) for row in matches}
        matches=[row for row in matches if str(row['id']) not in unavailable]
        matches=order_media(bounded_members(matches,[],config),config)
        obj = self._owned(record)
        existing_collections=None
        if obj is None:
            existing_collections=[item for item in self.section.collections()
                if vars(item).get('librarySectionID') is None or str(vars(item)['librarySectionID'])==self.section_id]
            exact=[item for item in existing_collections if item.title==title]
            owned=[item for item in exact if plex_has_collection_marker(item,'vodum:collection:'+record['id'])]
            if len(owned)>1:
                raise CollectionOwnershipError('collections.ownership_failed')
            if owned:
                recovered={**record,'remote_id':str(owned[0].ratingKey)}
                obj=self._owned(recovered)
                if obj is not None:
                    record_created(recovered['remote_id'])
            if obj is None and exact:
                raise CollectionOwnershipError('collections.title_collision',conflict={
                    'title':title,'library_section_id':self.section_id,
                    'remote_ids':[str(item.ratingKey) for item in exact]})
        warnings = ['collections.media_unavailable:'+media_id for media_id in sorted(skipped)]
        current_order = []
        membership_pending=False
        created_now=obj is None
        if created_now:
            existing_titles = {existing.title for existing in existing_collections}
            if 'VODUM '+record['id'] in existing_titles:
                raise CollectionOwnershipError('collections.ownership_failed')
            # Keep the initial URI bounded even for a continent with 30k titles.
            seed=matches[:100]
            try:
                obj = self.section.createCollection(title=title, items=[row['item'] for row in seed])
            except BadRequest:
                # Revalidate only the rejected seed, not the entire library.
                missing={str(row['id']) for row in seed if self._confirm_missing_media(row['item'])}
                if not missing:raise
                unavailable.update(missing)
                warnings.extend('collections.media_unavailable:'+key for key in sorted(missing))
                matches=[row for row in matches if str(row['id']) not in unavailable]
                seed=matches[:100]
                if not seed:raise ValueError('collections.publication_failed')
                # Never create a duplicate after an ambiguous server response.
                if any(item.title==title for item in self.section.collections()):
                    raise CollectionOwnershipError('collections.title_collision')
                obj=self.section.createCollection(title=title,items=[row['item'] for row in seed])
            # Persist the ID before any further mutation; never lose it on a later error.
            record_created(str(obj.ratingKey))
            self._mark_created(obj, record)
            self.publication_changes+=1
        # New collections already have their final name. Finalize legacy
        # temporary objects before expensive membership work.
        pending_presentation=created_now or obj.title=='VODUM '+record['id']
        if pending_presentation:
            confirm_title=isinstance(obj.title,str) and obj.title=='VODUM '+record['id']
            if obj.title!=title:
                try:
                    self._rename_owned(obj,record,title)
                except ValueError as exc:
                    if str(exc)!='collections.plex_title_rejected':raise
                    # Recover a legacy temporary collection whose rename Plex
                    # persistently refuses. Only replace our verified object.
                    if not plex_has_collection_marker(obj,'vodum:collection:'+record['id']):
                        raise CollectionOwnershipError('collections.ownership_failed')
                    if any(item.title==title for item in self.section.collections()):
                        raise CollectionOwnershipError('collections.title_collision')
                    replacement=self.section.createCollection(title=title,items=[row['item'] for row in matches[:100]])
                    self._track_replacement(record,obj.ratingKey)
                    record_created(str(replacement.ratingKey))
                    try:
                        self._mark_created(replacement,record)
                    except CollectionRunCancelled:
                        # Keep the persisted new ID for recovery. Cancellation
                        # must not trigger compensating remote deletions.
                        raise
                    except Exception:
                        # This object came from our create call. Restore the
                        # previous reference and remove only the failed new one.
                        record_created(str(obj.ratingKey))
                        replacement.delete()
                        raise
                    obj.delete()
                    db=vars(self).get('collection_db')
                    if db is not None:
                        db.execute('DELETE FROM collection_replaced_objects WHERE object_id=? AND remote_id=?',
                            (record['id'],str(obj.ratingKey)))
                    obj=replacement
                    seed=matches[:100]
                    created_now=True
                    confirm_title=False
                    self.publication_changes+=1
            if confirm_title:
                obj.reload()
                if obj.title!=title:raise RuntimeError('collections.publication_failed')
            obj.title = title
            obj.editSummary(config['summary'])
        # A cancellation after persisting the new ID may have left its old
        # temporary predecessor behind. Recheck ownership before retiring it.
        self._cleanup_replacements(record,obj)
        # Collection-list priority must survive a later membership timeout.
        sort_title=collection_sort_title(record,config,title)
        if vars(obj).get('titleSort')!=sort_title:
            obj.editSortTitle(sort_title)
            obj.titleSort=sort_title
        if portrait_path(config.get('profile_path')):
            try:
                obj.uploadPoster(url='https://image.tmdb.org/t/p/w500'+config['profile_path'])
            except CollectionRunCancelled:
                raise
            except Exception:
                log_handled_failure('collections.poster')
                warnings.append('collections.poster_failed')
        elif config.get('collection_poster'):
            try:
                path=collection_poster(config['collection_poster'])
                if path and (pending_presentation or artwork_changed(self,record,obj.ratingKey,path) or not plex_has_custom_poster(obj)):
                    self.heartbeat()
                    obj.uploadPoster(filepath=str(path))
                    remember_artwork(self,record,obj.ratingKey,path)
            except CollectionRunCancelled:raise
            except Exception:
                log_handled_failure('collections.poster')
                warnings.append('collections.poster_failed')

        native_release=config.get('native_release_order') is True and config.get('sort')=='release'
        sort_mode='release' if native_release else 'custom'
        sort_value=0 if native_release else 2
        if vars(obj).get('collectionSort')!=sort_value:
            obj.sortUpdate(sort=sort_mode)
            obj.collectionSort=sort_value
            # Read membership in its actual custom order after changing mode.
            vars(obj).pop('_items',None)

        if obj is not None:
            # PlexAPI's default 100-item pages make a 10k-member collection
            # spend over 100 rate-limited requests just reading membership.
            if created_now:
                items=[]
            elif isinstance(obj,PlexCollection):
                items=obj.fetchItems(obj.key+'/children',container_size=1000)
            else:
                items=obj.items()
            current = {str(row['id']):row['item'] for row in seed} if created_now else {str(item.ratingKey):item for item in items}
            # The mutation allowance starts after reading the snapshot. A large
            # collection must still be able to make progress on each resumption.
            deadline=time.monotonic()+min(self.publication_budget_seconds,config.get('publication_budget_seconds',self.publication_budget_seconds))
            matches=bounded_members(matches,[{'id':key,'item':item} for key,item in current.items()],config)
            matches=order_media(matches,config)
            desired = {str(row['id']):row['item'] for row in matches}
            current_order = list(current)
            additions = [value for key,value in desired.items() if key not in current]
            removable=removable_member_ids(current,desired,config)
            removals = [value for key,value in current.items() if key in removable]
            if additions:
                for start in range(0,len(additions),100):
                    batch=additions[start:start+100]
                    if time.monotonic()>=deadline:
                        membership_pending=True
                        break
                    try:
                        obj.addItems(batch)
                        self.publication_changes+=len(batch)
                        current_order.extend(str(item.ratingKey) for item in batch)
                    except BadRequest:
                        # A stale snapshot can contain a removed Plex ID. A
                        # rejected batch must not block all the valid members.
                        for item in batch:
                            if time.monotonic()>=deadline:
                                membership_pending=True
                                break
                            try:
                                obj.addItems([item])
                                self.publication_changes+=1
                                current_order.append(str(item.ratingKey))
                            except BadRequest:
                                warnings.append('collections.media_unavailable:'+str(item.ratingKey))
                                if self._confirm_missing_media(item):
                                    unavailable.add(str(item.ratingKey))
                                    log_handled_failure('collections.publish.member',level='warning',media_id=int(item.ratingKey))
                                else:
                                    membership_pending=True
                                    log_handled_failure('collections.publish.member',level='error',media_id=int(item.ratingKey))
            if unavailable:
                matches=[row for row in matches if str(row['id']) not in unavailable]
                desired={key:value for key,value in desired.items() if key not in unavailable}
            if membership_pending:warnings.append('collections.membership_pending')
            if not membership_pending and removals:
                # Plex's bulk metadata API supports removing one named tag
                # from explicit IDs. Do not reset collection tags or lock the
                # field: other collections and user metadata must stay intact.
                # A comma in the name is ambiguous in Plex's tag-removal list;
                # keep the ID-scoped individual endpoint in that case.
                bulk=(len(removals)>=100 and isinstance(obj.title,str) and obj.title
                      and ',' not in obj.title and hasattr(self,'section_id')
                      and all(str(item.ratingKey).isdigit() for item in removals))
                if bulk:
                    for start in range(0,len(removals),100):
                        if time.monotonic()>=deadline:
                            membership_pending=True
                            break
                        batch=removals[start:start+100]
                        params={'id':','.join(str(item.ratingKey) for item in batch),
                                'type':1 if self.section.type=='movie' else 2,
                                'collection[].tag.tag-':quote(obj.title)}
                        try:
                            self.plex.query('/library/sections/'+self.section_id+'/all?'+urlencode(params),method=self.plex._session.put)
                        except (BadRequest,NotFound):
                            # Older servers can reject multi-edits. Keep the
                            # previous path, subject to the same time budget.
                            removals=removals[start:]
                            break
                        removed={str(item.ratingKey) for item in batch}
                        self.publication_changes+=len(removed)
                        current_order=[key for key in current_order if key not in removed]
                    else:removals=[]
                    if membership_pending:removals=[]
                for item in removals:
                    if time.monotonic()>=deadline:
                        membership_pending=True
                        break
                    try:
                        obj.removeItems([item])
                        self.publication_changes+=1
                    except NotFound:pass  # Already removed by a concurrent library edit.
                    current_order.remove(str(item.ratingKey))
                if membership_pending:warnings.append('collections.membership_pending')
        if not pending_presentation:
            if obj.title!=title:self._rename_owned(obj,record,title)
            # PlexAPI edits remotely without updating this object's cache.
            obj.title = title
            if vars(obj).get('summary')!=config['summary']:obj.editSummary(config['summary'])
        previous = None
        desired_order=[str(match['id']) for match in matches]
        desired_keys=set(desired_order)
        # Unknown members preserved during partial discovery must remain, but
        # must not sit ahead of the selected ranking. Only the prefix before
        # such a member can be kept without moving an unselected item.
        first_preserved=next((index for index,key in enumerate(current_order) if key not in desired_keys),len(current_order))
        stationary=stationary_members(current_order[:first_preserved],desired_order)
        # During a first library-wide discovery, the selection is still
        # growing. Publish members now and sort once discovery has finished.
        defer_order=config.get('_defer_order') is True
        if defer_order and not native_release and current_order[:len(desired_order)]!=desired_order:
            warnings.append('collections.order_pending')
        for match in matches:
            if native_release:break
            if membership_pending:break
            if defer_order:break
            key = str(match['id'])
            if key not in stationary:
                if time.monotonic()>=deadline:
                    warnings.append('collections.order_pending')
                    break
                try:
                    self._move_collection_item(obj,match['item'],after=previous)
                except BadRequest as exc:
                    # Keep provider payloads out of public diagnostics.
                    raise ValueError('collections.plex_order_rejected') from exc
                self.publication_changes+=1
            previous = match['item']
        warnings.extend(self.apply_visibility(record,config,obj=obj))

        return warnings

    def apply_visibility(self, record, config, *, obj=None):
        with visibility_lock(record):
            return self._apply_visibility(record,config,obj=obj)

    def _apply_visibility(self, record, config, *, obj=None):
        config=priority_config(vars(self).get('collection_db'),record,config)
        obj=obj if obj is not None else self._owned(record)
        if obj is None:return []
        warnings=[]
        presentation_changed=False
        if not config.get('_visibility_only') and isinstance(obj.title,str) and obj.title=='VODUM '+record['id']:
            # Old successful runs may have left state='synced' on a temporary
            # object. Repair by verified remote ID, independent of discovery.
            target=record.get('title')
            if not isinstance(target,str) or not target or target==obj.title:
                raise RuntimeError('collections.publication_failed')
            poster=object_poster_key(record,config)
            if poster:
                try:
                    self.heartbeat()
                    obj.uploadPoster(filepath=str(collection_poster(poster)))
                except CollectionRunCancelled:raise
                except Exception:
                    log_handled_failure('collections.poster.repair',level='error')
                    warnings.append('collections.poster_failed')
                    # Keep the recognizable temporary name until the artwork
                    # succeeds, so an ordinary later pass can retry this repair.
                    return warnings
            self._rename_owned(obj,record,target)
            obj.reload()
            if obj.title!=target:
                raise RuntimeError('collections.publication_failed')
            obj.editSummary(config.get('summary') or target+' · VODUM')
        sort_title=collection_sort_title(record,config,obj.title)
        if not config.get('_visibility_only') and vars(obj).get('titleSort')!=sort_title:
            obj.editSortTitle(sort_title)
            obj.titleSort=sort_title
            presentation_changed=True
        visibility=obj.visibility()
        if visibility is None:raise RuntimeError('collections.publication_failed')
        destinations=collection_visibility(config)
        if (any(destinations.values()) and isinstance(visibility.title,str)
                and isinstance(obj.title,str) and visibility.title!=obj.title
                and getattr(visibility,'deletable',False) is True
                and getattr(visibility,'_promoted',False) is True):
            # Promoted hubs keep their own title after a collection rename.
            # Recreate only this owned collection's recommendation, then apply
            # its configured destinations and position as for a fresh hub.
            self.heartbeat()
            visibility.remove()
            visibility=obj.visibility()
            presentation_changed=True
        current_destinations={key:vars(visibility).get(field) for key,field in
            (('home','promotedToOwnHome'),('shared','promotedToSharedHome'),('recommended','promotedToRecommended'))}
        if current_destinations!=destinations:
            visibility.updateVisibility(**destinations)
            presentation_changed=True
        if isinstance(vars(self).get('_verified_presentations'),dict):
            self._verified_presentations[record['id']]=(obj,visibility)
        db=vars(self).get('collection_db')
        if vars(self).get('defer_library_reorder'):
            return warnings
        if db is not None and presentation_changed and record.get('instance_id'):
            # Newly promoted/recreated hubs get a Plex default position. Queue
            # a durable library reorder after publication, including children.
            from core.collections_control import queue_control
            with db.transaction() as cursor:
                queue_control(cursor,record['instance_id'],priority=True)
        # Membership updates must not trigger a library-wide HTTP traversal.
        # Explicit priority commands own recommendation ordering.
        if db is None and any(destinations.values()):
            visibility.move(after=None)
        return warnings

    def reorder_owned_collections(self, db, *, current_record=None, current_obj=None):
        """Order VODUM hubs by configuration priority, never external hubs."""
        library_id=vars(self).get('collection_library_id')
        if library_id is None:
            return
        records=[dict(row) for row in db.query("""SELECT o.*,i.config_json FROM collection_objects o
            JOIN collection_instances i ON i.id=o.instance_id
            WHERE i.library_id=? AND i.enabled=1 AND i.retired=0
              AND o.remote_id IS NOT NULL AND o.state!='deleted'
            ORDER BY i.created_at,i.id,o.title,o.id""",(library_id,))]
        if current_record and current_obj is not None:
            for row in records:
                if row['id']==current_record['id']:row['title']=current_obj.title
        for row in records:
            row['priority_config']=priority_config(db,row,json.loads(row['config_json']))
        records.sort(key=lambda row:collection_sort_title(row,row['priority_config'],row['title']))
        hubs=list(self.section.managedHubs())
        ordered=[];warnings=[]
        for row in records:
            self.heartbeat()
            config=row['priority_config']
            if config.get('mode')=='arr' or not any(collection_visibility(config).values()):continue
            try:
                verified=vars(self).get('_verified_presentations',{}).get(row['id'])
                obj=verified[0] if verified else current_obj if current_record and row['id']==current_record['id'] else self._owned(row)
                if obj is None:continue
                sort_title=collection_sort_title(row,config,row['title'])
                if vars(obj).get('titleSort')!=sort_title:
                    obj.editSortTitle(sort_title)
                    obj.titleSort=sort_title
                if not any(collection_visibility(config).values()):continue
                visibility=verified[1] if verified else obj.visibility()
                hub=next((hub for hub in hubs if hub.identifier==visibility.identifier),None)
                if hub is not None:ordered.append(hub)
            except CollectionRunCancelled:raise
            except (requests.exceptions.ConnectionError,requests.exceptions.Timeout):
                # Stop this pass after one transport failure instead of paying
                # a full timeout for each sibling. No hub moves use a partial order.
                log_handled_failure('collections.priority.object',level='warning')
                return ['collections.priority_not_applied']
            except Exception:
                # One unavailable/unverified sibling must not block the others.
                log_handled_failure('collections.priority.object',level='error')
                warnings.append('collections.priority_not_applied')
        # Simulate each move locally to avoid requests when already ordered.
        previous=None
        for index,hub in enumerate(ordered):
            current=next(i for i,item in enumerate(hubs) if item.identifier==hub.identifier)
            if current!=index:
                self.heartbeat()
                hub.move(after=previous)
                hubs.insert(index,hubs.pop(current))
            previous=hub
        return list(dict.fromkeys(warnings))

    def _move_collection_item(self, obj, item, *, after=None):
        try:
            return obj.moveItem(item,after=after)
        except BadRequest:
            # Some collection objects expose a metadata key. PMS documents the
            # collection endpoint for reordering; retry only when it differs.
            if not isinstance(obj,PlexCollection) or obj.smart:
                raise
            identifiers=[obj.ratingKey,item.ratingKey]+([after.ratingKey] if after is not None else [])
            if any(not str(value).isdigit() or int(value)<=0 for value in identifiers):raise
            endpoint='/library/collections/'+str(obj.ratingKey)
            if obj.key==endpoint:raise
            key=endpoint+'/items/'+str(item.ratingKey)+'/move'
            if after is not None:key+='?after='+str(after.ratingKey)
            obj._server.query(key,method=obj._server._session.put)
            return obj

    def add_to_front(self, record, row):
        """A cycle addition changes membership/order, not every metadata field."""
        obj = self._owned(record)
        if obj is None:
            raise RuntimeError('collections.publication_failed')
        items = obj.items()
        if not any(str(item.ratingKey)==str(row['id']) for item in items):
            obj.addItems([row['item']])
        if vars(obj).get('collectionSort') != 2:
            obj.sortUpdate(sort='custom')
            previous = None
            for item in items:
                self._move_collection_item(obj,item,after=previous)
                previous = item
        self._move_collection_item(obj,row['item'],after=None)

    def remove_member(self, record, row):
        obj = self._owned(record)
        if obj is not None:
            obj.removeItems([row['item']])

    def delete(self, record):
        obj = self._owned(record)
        self._cleanup_replacements(record,obj)
        if obj is not None:
            obj.visibility().updateVisibility(recommended=False,home=False,shared=False)
            obj.delete()  # Collection metadata only. No media delete endpoints.


class JellyfinCollections:
    def __init__(self, server, library):
        self.heartbeat = lambda: None
        self.http = server_http_session(server, retry_reads=True)
        self.headers = jellyfin_headers(server.get('token'))
        self.bases = list(dict.fromkeys(str(server.get(key) or '').strip().rstrip('/') for key in ('url','local_url','public_url')
            if str(server.get(key) or '').strip().lower().startswith(('http://','https://'))))
        if not self.bases:
            raise ValueError('collections.inventory_address_invalid')
        self.base = self.bases[0]
        self.section_id = library['section_id']
        self.media_type = 'Movie' if library['type'] in ('movie','movies','film','films') else 'Series'

    def close(self):
        self.http.close()

    def request(self, method, path, *, params=None, data=None, missing_ok=False):
        # GET /Items/{id} requires a user context in Jellyfin. API keys do
        # support the global Items query; request the exact ID and fields there.
        single_item=method.upper()=='GET' and re.fullmatch(r'/Items/[^/]+',path) is not None
        if single_item:
            item_id=path.rsplit('/',1)[1]
            params={**(params or {}),'Ids':item_id,'Fields':'Tags,ProviderIds,MediaSources,MediaStreams,Overview'}
            path='/Items'
        # Retry only reads on explicitly configured addresses. Never replay a
        # mutation whose response may have been lost after the remote commit.
        bases = [self.base,*[base for base in getattr(self,'bases',[]) if base!=self.base]] if method.upper() in ('GET','HEAD') else [self.base]
        for index,base in enumerate(bases):
            self.heartbeat()
            try:
                response = self.http.request(method,base+path,headers=self.headers,params=params,json=data,timeout=30)
            except requests.exceptions.SSLError:
                raise
            except (requests.exceptions.ConnectionError,requests.exceptions.Timeout):
                if index==len(bases)-1: raise
                continue
            if response.status_code in (502,503,504) and index<len(bases)-1:
                response.close()
                continue
            if missing_ok and response.status_code==404:
                self.base = base
                return None
            try:response.raise_for_status()
            except requests.HTTPError as exc:
                exc.collection_operation='read_item' if single_item else ('create_collection' if path=='/Collections' else 'jellyfin_request')
                raise
            self.base = base
            payload=response.json() if response.content else {}
            if single_item:
                rows=payload.get('Items') if isinstance(payload,dict) else None
                if not isinstance(rows,list):raise ValueError('collections.jellyfin_response_invalid')
                matches=[row for row in rows if isinstance(row,dict) and str(row.get('Id','')).replace('-','').lower()==item_id.replace('-','').lower()]
                if not matches and missing_ok:return None
                if len(matches)!=1:raise ValueError('collections.jellyfin_item_unavailable')
                return matches[0]
            return payload

    def _items(self, params):
        output, offset = [], 0
        while True:
            data = self.request('GET','/Items',params={**params,'StartIndex':offset,'Limit':250})
            rows = data.get('Items') if isinstance(data, dict) else None
            total = data.get('TotalRecordCount') if isinstance(data, dict) else None
            if not isinstance(rows, list) or type(total) is not int:
                raise ValueError('collections.inventory_invalid')
            output.extend(rows)
            offset += len(rows)
            if offset == total:
                break
            if offset > total or not rows:
                raise ValueError('collections.inventory_invalid')
        return output

    def inventory(self):
        return [{'id':row['Id'], 'tmdb':str((row.get('ProviderIds') or {}).get('Tmdb') or ''),
                 'imdb':str((row.get('ProviderIds') or {}).get('Imdb') or ''),
                 'tvdb':str((row.get('ProviderIds') or {}).get('Tvdb') or ''),
                 'title':row['Name'],'original_title':row.get('OriginalTitle'),'year':row.get('ProductionYear'),
                 'rating':row.get('CommunityRating'), 'added_at':row.get('DateCreated'), 'release_date':row.get('PremiereDate'), 'item':row,
                 'countries':row.get('ProductionLocations') or [],'genres':row.get('Genres') or [],'tags':row.get('Tags') or [],'summary':row.get('Overview'),
                 'people':{'actors':[p['Name'] for p in (row.get('People') or []) if p.get('Type')=='Actor' and p.get('Name')],
                           'directors':[p['Name'] for p in (row.get('People') or []) if p.get('Type')=='Director' and p.get('Name')]}} for row in self._items({
                     'ParentId':self.section_id,'Recursive':'true','IncludeItemTypes':self.media_type,'Fields':'CommunityRating,DateCreated,ProviderIds,OriginalTitle,ProductionYear,PremiereDate,People,Genres,Tags,Overview,ProductionLocations'})]

    def collection_members(self, record):
        obj = self._owned(record)
        if obj is None:
            return []
        return [{'id':row['Id'],'title':row['Name'],'tmdb':str((row.get('ProviderIds') or {}).get('Tmdb') or ''),
                 'release_date':row.get('PremiereDate'),'item':row} for row in self._items({'ParentId':obj['Id'],'Recursive':'false','Fields':'ProviderIds,MediaSources,MediaStreams'})]

    def has_audio(self, row, language):
        item = self.request('GET','/Items/'+quote(row['id'],safe=''))
        if item.get('Type')=='Series':
            episodes=self._items({'ParentId':row['id'],'Recursive':'true','IncludeItemTypes':'Episode','Fields':'MediaSources,MediaStreams'})
            return bool(episodes) and all(self.has_audio({'id':episode['Id']},language) for episode in episodes)
        sources = item.get('MediaSources') or [{'MediaStreams':item.get('MediaStreams') or []}]
        return any(any(stream.get('Type')=='Audio' and audio_language(stream.get('Language'),language)
                       for stream in source.get('MediaStreams') or []) for source in sources)

    def _owned(self, record):
        if not record['remote_id']:
            return None
        obj = self.request('GET','/Items/'+quote(record['remote_id'],safe=''),missing_ok=True)
        if obj is None:
            return None
        marker = 'vodum:collection:' + record['id']
        pending = record.get('state')=='created' and obj.get('Name')=='VODUM '+record['id']
        if obj.get('Type') != 'BoxSet' or not pending and marker not in (obj.get('Tags') or []):
            raise CollectionOwnershipError('collections.ownership_failed')
        return obj

    def sync(self, record, title, matches, config, record_created):
        matches=order_media(bounded_members(matches,[],config),config)
        config=priority_config(vars(self).get('collection_db'),record,config)
        obj = self._owned(record)
        if obj is None:
            existing = self._items({'Recursive':'true','IncludeItemTypes':'BoxSet'})
            if any(item.get('Name') == title for item in existing):
                raise CollectionOwnershipError('collections.title_collision')
            if any(item.get('Name') == 'VODUM '+record['id'] for item in existing):
                raise CollectionOwnershipError('collections.ownership_failed')
            # Jellyfin may reuse an existing boxset by name. Create under a
            # unique temporary name, persist its returned ID, then label/rename.
            created = self.request('POST','/Collections',params={'name':'VODUM '+record['id'],
                'ids':','.join(row['id'] for row in matches),'isLocked':'true'})
            remote_id = str(created['Id'])
            record_created(remote_id)
            obj = self.request('GET','/Items/'+quote(remote_id,safe=''))
        marker = 'vodum:collection:'+record['id']
        if marker not in (obj.get('Tags') or []):
            obj['Tags'] = [*(obj.get('Tags') or []),marker]
        remote_id = str(obj['Id'])
        sort_title=collection_sort_title(record,config,title)
        obj.update(Name=title,SortName=sort_title,ForcedSortName=sort_title,Overview=config['summary'],LockData=True)
        self.request('POST','/Items/'+remote_id,data=obj)
        current = {item['Id'] for item in self._items({'ParentId':remote_id,'Recursive':'false'})}
        matches=bounded_members(matches,[{'id':key} for key in sorted(current)],config)
        desired = {row['id'] for row in matches}
        if desired-current:
            self.request('POST','/Collections/'+remote_id+'/Items',params={'ids':','.join(sorted(desired-current))})
        removable=removable_member_ids(current,desired,config)
        if removable:
            self.request('DELETE','/Collections/'+remote_id+'/Items',params={'ids':','.join(sorted(removable))})
        warnings = ['collections.jellyfin_order_not_supported']
        if any(collection_visibility(config).values()):
            warnings.append('collections.jellyfin_home_not_supported')
        if portrait_path(config.get('profile_path')):
            try:
                image = fetch_portrait(config['profile_path'],size='w500')
                if not image:
                    raise RuntimeError('Portrait unavailable')
                data,content_type = image
                self.heartbeat()
                response = self.http.request('POST',self.base+'/Items/'+quote(remote_id,safe='')+'/Images/Primary',
                    headers={**self.headers,'Content-Type':content_type},data=base64.b64encode(data),timeout=30)
                response.raise_for_status()
            except CollectionRunCancelled:
                raise
            except Exception:
                log_handled_failure('collections.poster')
                warnings.append('collections.poster_failed')
        elif config.get('collection_poster'):
            try:
                path=collection_poster(config['collection_poster'])
                if path and (artwork_changed(self,record,remote_id,path) or not (obj.get('ImageTags') or {}).get('Primary')):
                    self.heartbeat()
                    response=self.http.request('POST',self.base+'/Items/'+quote(remote_id,safe='')+'/Images/Primary',
                        headers={**self.headers,'Content-Type':'image/jpeg' if path.suffix=='.jpg' else 'image/png'},data=base64.b64encode(path.read_bytes()),timeout=30)
                    response.raise_for_status()
                    remember_artwork(self,record,remote_id,path)
            except CollectionRunCancelled:raise
            except Exception:
                log_handled_failure('collections.poster')
                warnings.append('collections.poster_failed')

        return warnings

    def apply_visibility(self, record, config):
        with visibility_lock(record):
            return self._apply_visibility(record,config)

    def _apply_visibility(self, record, config):
        config=priority_config(vars(self).get('collection_db'),record,config)
        if config.get('_visibility_only'):
            return ['collections.jellyfin_home_not_supported'] if any(collection_visibility(config).values()) else []
        obj=self._owned(record)
        if obj is not None:
            sort_title=collection_sort_title(record,config,obj['Name'])
            obj.update(SortName=sort_title,ForcedSortName=sort_title)
            self.request('POST','/Items/'+quote(str(obj['Id']),safe=''),data=obj)
        return ['collections.jellyfin_home_not_supported'] if any(collection_visibility(config).values()) else []

    def delete(self, record):
        obj = self._owned(record)
        if obj is None:
            return
        remote_id = str(obj['Id'])
        members = self._items({'ParentId':remote_id,'Recursive':'false'})
        if members:
            self.request('DELETE','/Collections/'+remote_id+'/Items',params={'ids':','.join(item['Id'] for item in members)})
        if self._items({'ParentId':remote_id,'Recursive':'false'}):
            raise RuntimeError('Refusing to delete a nonempty Jellyfin collection')
        self.request('DELETE','/Items/'+remote_id)


def media_adapter(server, library):
    if str(server['type']).strip().lower() == 'plex':
        return PlexCollections(server,library)
    if str(server['type']).strip().lower() == 'jellyfin':
        return JellyfinCollections(server,library)
    raise ValueError('collections.invalid_library')
