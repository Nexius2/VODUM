from core.collections_ordering import order_media
"""Spotlight adapter for the supplied Selection du moment cycle.

Uses VODUM's keys, server connections, ownership fence and task heartbeat.
No configuration or credentials from the supplied application are imported.
"""
import json
import os
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from datetime import date, datetime, timedelta
from dateutil.tz import gettz

from core.collections_media import media_adapter
from core.collection_inventory import CachedCollectionMedia
from core.collections_memoria_source import MemoriaSource
from core.collections_repository import collection_settings, stamp, utcnow, CollectionRunCancelled
from core.collections_spotlight_cycle import Engine
from core.collections_spotlight_rules import recent_movie_start, recent_movie_end, initial_release, digital_events
from core.collections_spotlight_store import CycleStore
from core.error_reporting import log_handled_failure
from secret_store import decrypt_secret
from logging_utils import get_logger
import time


def cycle_config(config, zone):
    return {'scheduler':{'timezone':zone},
            'collection':{'limit':config.get('limit',0),'retention_days':config.get('retention',30),'release_window_days':config.get('release_window_days',30)},
            'exclusions':{'manual_removal_cooldown_days':30},
            'scoring':{'min_score':config.get('min_score',65),'minimum_votes':100,'high_rating_threshold':7,
                'profiles':{'blockbuster_popularity':50,'high_rated_popularity':5,'franchise_popularity':20,
                            'trending_popularity':15,'trend_strength':.5},
                'weights':{'freshness':25,'popularity':35,'rating':25,'trending':10,'franchise':5}}}


class SpotlightDiscovery(MemoriaSource):
    partial = False

    def discover(self, now, config):
        self.partial = False
        today = now.date()
        start = today-timedelta(days=config['collection']['release_window_days']-1)
        end = recent_movie_end(today)
        self.stats = getattr(self,'stats',{})
        self.stats.update(local_candidates=len(self.library_ids),details_checked=0,rejected_release=0,rejected_digital=0)
        self.stats['source_failures']=[]
        if not self.library_ids:
            return
        trending = {}
        try:
            trending = {row['id']:i for i,row in enumerate(self.tmdb('/trending/movie/week')['results'])}
        except CollectionRunCancelled:
            raise
        except Exception as exc:
            self.partial = True
            self.stats['source_failures'].append({'stage':'trending','error_type':type(exc).__name__})
            log_handled_failure('collections.spotlight.trending')
        # Eligibility requires a recent, dated local movie. Inspect that bounded
        # set directly instead of paging through the worldwide release catalog
        # and intersecting it with the library afterwards. Digital dates, score,
        # trend and audio rules stay authoritative.
        for media_id in sorted(self.library_ids):
            try:
                movie = self.tmdb('/movie/'+str(media_id),append_to_response='release_dates')
                self.stats['details_checked'] += 1
                first = initial_release(movie)
                if movie.get('adult') or first is None or not recent_movie_start(today)<=first<=end:
                    self.stats['rejected_release'] += 1
                    continue
                events = digital_events(movie,start,end)
                if events:
                    movie.update(events=events,initial_release=first,
                        trend=1-trending[media_id]/max(len(trending),1) if media_id in trending else 0)
                    yield movie
                else:
                    self.stats['rejected_digital'] += 1
            except CollectionRunCancelled:
                raise
            except Exception as exc:
                self.partial = True
                self.stats['source_failures'].append({'stage':'movie_details','tmdb_id':media_id,'error_type':type(exc).__name__})
                log_handled_failure('collections.spotlight.candidate')


@dataclass
class Movie:
    key: str
    tmdb: int | None
    title: str
    raw: dict
    release_date: date | None

    @property
    def label(self):
        return self.title


class SpotlightLibrary:
    def __init__(self, db, instance, adapter, config, heartbeat, preview):
        self.db,self.instance,self.adapter,self.config,self.heartbeat,self.preview = db,instance,adapter,config,heartbeat,preview
        row = db.query_one("SELECT * FROM collection_objects WHERE instance_id=? AND person_key='spotlight'",(instance['id'],))
        self.record = dict(row) if row else {'id':str(uuid.uuid4()),'instance_id':instance['id'],'person_key':'spotlight',
            'remote_id':None,'title':instance['name'],'state':'reserved'}
        self.ordered = getattr(adapter,'supports_order',False)
        self.rows = None
        self._members = None
        self.last_confirmed_members = None
        self.warnings = []

    def movie(self, row):
        raw_date = row.get('release_date')
        if not raw_date:
            item = row['item']
            raw_date = vars(item).get('originallyAvailableAt') if not isinstance(item,dict) else item.get('PremiereDate')
        if isinstance(raw_date,datetime):
            raw_date = raw_date.date()
        if not isinstance(raw_date,date):
            try: raw_date = date.fromisoformat(str(raw_date)[:10])
            except ValueError: raw_date = None
        tmdb = str(row.get('tmdb') or '')
        return Movie(str(row['id']),int(tmdb) if tmdb.isdigit() else None,row['title'],row,raw_date)

    def library(self):
        if self.rows is None:
            self.rows = self.adapter.inventory()
        return [self.movie(row) for row in self.rows]

    def members(self):
        if self._members is None:
            self._members = [self.movie(row) for row in self.adapter.collection_members({**self.record,'read_only':self.preview})] if self.record['remote_id'] else []
        self.last_confirmed_members = list(self._members)
        return list(self._members)

    def has_french_audio(self, movie):
        return self.adapter.has_audio(movie.raw,self.config.get('audio_language','fr'))

    def publish(self, rows):
        rows=order_media(rows,self.config)
        self.heartbeat()
        if not rows and collection_settings(self.db)['suppress_empty']:
            if self.record['remote_id']:
                self.adapter.delete(self.record)
                self.db.execute("UPDATE collection_objects SET remote_id=NULL,state='deleted' WHERE id=?",(self.record['id'],))
                self.record.update(remote_id=None,state='deleted')
                self._members = []
            return
        if not rows and not self.record['remote_id']:
            return
        if not self.db.query_one('SELECT id FROM collection_objects WHERE id=?',(self.record['id'],)):
            self.db.execute("INSERT INTO collection_objects(id,instance_id,person_key,title) VALUES(?,?,'spotlight',?)",
                (self.record['id'],self.instance['id'],self.instance['name']))
        def created(remote_id):
            self.record.update(remote_id=remote_id,state='created')
            self.db.execute("UPDATE collection_objects SET remote_id=?,state='created' WHERE id=?",(remote_id,self.record['id']))
        # A failed response may still have committed remotely. Never reuse the
        # pre-mutation membership snapshot for recovery or final publication.
        self._members = None
        warnings = self.adapter.sync(self.record,self.instance['name'],rows,{**self.config,'collection_poster':'spotlight','summary':self.instance['name']},created)
        self.warnings.extend(warnings or [])
        self._members = None
        actual = self.members()
        if {str(row['id']) for row in rows}!={movie.key for movie in actual}:
            self.record['state'] = 'unconfirmed'
            raise ValueError('collections.publication_failed')
        self.record['state'] = 'synced'
        self.db.execute("UPDATE collection_objects SET state='synced' WHERE id=?",(self.record['id'],))

    def add(self, movie):
        incremental = getattr(self.adapter,'add_to_front',None)
        if self.record['remote_id'] and self.record['state']=='synced' and callable(incremental):
            self._members = None
            incremental(self.record,movie.raw)
        else:
            self.publish([movie.raw,*[item.raw for item in self.members() if item.key!=movie.key]])

    def remove(self, movie):
        incremental = getattr(self.adapter,'remove_member',None)
        if self.record['remote_id'] and callable(incremental):
            self._members = None
            incremental(self.record,movie.raw)
        else:
            self.publish([item.raw for item in self.members() if item.key!=movie.key])

    def move_to_front(self, movie):
        self.add(movie)
        members = self.members()
        if self.ordered and (not members or members[0].key!=movie.key):
            raise RuntimeError('collections.publication_failed')


def run_spotlight(db, instance, *, kind='sync', heartbeat=lambda:None,
                  source_factory=SpotlightDiscovery, adapter_factory=media_adapter):
    config = json.loads(instance['config_json'])
    config['_order_seed']=uuid.uuid4().hex
    preview = kind=='preview'
    library = dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server = dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    result = {'people':[],'present':0,'missing':0,'arr_requests':0,'warnings':[],'errors':[],
              'preview':preview,'diagnostics':{}}
    started = time.monotonic()
    def progress(stage, **counts):
        result['stage'] = stage
        result['diagnostics'].update(counts)
        result['elapsed_seconds'] = round(time.monotonic()-started,1)
        get_logger('collections').info('Spotlight instance=%s stage=%s elapsed=%.1fs counts=%s',
            instance['id'],stage,result['elapsed_seconds'],counts)
        reporter = getattr(heartbeat,'report',None)
        if callable(reporter): reporter(result)
        heartbeat()
    adapter = source = store = None
    bridge = engine = None
    try:
        progress('connection')
        adapter = CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
        adapter.heartbeat = heartbeat
        bridge = SpotlightLibrary(db,instance,adapter,config,heartbeat,preview)
        if kind in ('cleanup','delete'):
            progress('cleanup')
            if bridge.record['remote_id']:
                adapter.delete(bridge.record)
                db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(bridge.record['id'],))
            db.execute("UPDATE collection_spotlight_entries SET active=0,reason='disabled',removed=? WHERE instance_id=? AND active=1",(stamp(),instance['id']))
            result.update(deleted=1,outcome='cleanup')
            return result
        key = None
        if kind!='expire':
            shared = db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
            key = decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        source = source_factory(key,config['language']) if kind!='expire' else SimpleNamespace(close=lambda:None)
        source.heartbeat = heartbeat
        source.progress = progress
        source.stats = result['diagnostics']
        # Expiry-only work must not read the library inventory or discover films.
        if kind != 'expire':
            progress('inventory')
            movies = bridge.library()
            today = utcnow().astimezone(gettz(instance['timezone'])).date()
            source.library_ids = {movie.tmdb for movie in movies if movie.tmdb and movie.release_date
                and recent_movie_start(today)<=movie.release_date<=recent_movie_end(today)}
            result['diagnostics'].update(library_total=len(movies),library_with_tmdb=sum(bool(m.tmdb) for m in movies),
                missing_date=sum(m.release_date is None for m in movies),local_candidates=len(source.library_ids))
            if movies and not any(m.tmdb for m in movies):
                result['errors'].append('collections.spotlight_no_ids')
        store = CycleStore(db,instance['id'],preview)
        engine = Engine(cycle_config(config,instance['timezone']),store,bridge,source,dry=preview)
        result['spotlight'] = engine.report
        report = engine.run(mode='cleanup' if kind=='expire' else 'all',now=utcnow())
        result['diagnostics'].update(getattr(source,'stats',{}))
        if not preview:
            progress('publish')
            bridge.publish([item.raw for item in bridge.members()])
        members = bridge.members()
        if preview:
            # The simulated membership lives in the in-memory journal, not Plex.
            by_key = {movie.key:movie for movie in (bridge.library() if kind!='expire' else members)}
            members = [by_key[row['plex_id']] for row in store.query('SELECT * FROM entries WHERE active=1') if row['plex_id'] in by_key]
        by_key={movie.key:movie for movie in members}
        members=[by_key[str(row['id'])] for row in order_media([movie.raw for movie in members],config)]
        media = [{'tmdb_id':m.tmdb,'title':m.title,'media_type':'movie','present':True,'arr_status':'not_needed'} for m in members]
        failed = (bool(result['errors']) or bool(report.get('mutation_failures'))
                  or report.get('cleanup') in ('failed','partial') or report.get('population')=='failed')
        if not failed and any(report.get(key)=='partial' for key in ('cleanup','population')):
            result['warnings'].append('collections.spotlight_partial')
        published = bool(not preview and bridge.record['remote_id'] and bridge.record['state']=='synced')
        result.update(people=[{'person_key':'spotlight','name':instance['name'],'collection_title':instance['name'],
                          'published':published,'media':media,'selected':[m.title for m in members]}] if published or preview else [],
                present=len(members),outcome='preview' if preview else 'failed' if failed else 'published' if published else 'empty')
        result['warnings'].extend(bridge.warnings)
        if not preview and not published and not failed:
            result['warnings'].append('collections.spotlight_empty')
        if failed: result['errors'].append('collections.spotlight_failed')
        progress('complete',selected=len(members))
        return result
    except Exception as exc:
        if engine is not None: result['spotlight'] = engine.report
        # Preserve confirmed publications even if later work failed or was stopped.
        if bridge is not None and bridge.last_confirmed_members is not None and bridge.record['state']=='synced' and bridge.record['remote_id'] and not preview:
            members = bridge.last_confirmed_members
            result['people'] = [{'person_key':'spotlight','name':instance['name'],'collection_title':instance['name'],
                'published':True,'media':[{'tmdb_id':m.tmdb,'title':m.title,'media_type':'movie','present':True,'arr_status':'not_needed'} for m in members]}]
            result['present'] = len(members)
        exc.result = result
        raise
    finally:
        if store: store.close()
        if source: source.close()
        if adapter: adapter.close()
