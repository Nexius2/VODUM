"""Shared, atomic library snapshots. Collection engines never trigger a scan."""
import json
import uuid
import hashlib
import unicodedata
import requests
import sqlite3
import socket
import errno
from types import SimpleNamespace
from datetime import date, datetime, timedelta
from xml.etree.ElementTree import Element, SubElement

from core.collections_repository import stamp, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_inventory (
 library_id INTEGER PRIMARY KEY REFERENCES libraries(id) ON DELETE CASCADE,
 generation TEXT, scope TEXT, started_at TEXT, finished_at TEXT, completed_at TEXT,
 duration_seconds REAL, media_count INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'missing', last_error TEXT);
CREATE TABLE IF NOT EXISTS collection_inventory_media (
 library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
 media_id TEXT NOT NULL, data_json TEXT NOT NULL,
 PRIMARY KEY(library_id,media_id));
CREATE TABLE IF NOT EXISTS collection_inventory_audio (
 library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
 generation TEXT NOT NULL, media_id TEXT NOT NULL, language TEXT NOT NULL,
 available INTEGER NOT NULL, PRIMARY KEY(library_id,generation,media_id,language));
CREATE TABLE IF NOT EXISTS collection_inventory_runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
 duration_seconds REAL, libraries INTEGER NOT NULL DEFAULT 0,
 media_count INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0);
"""


def scope_key(server, library):
    scope = [server['id'],str(server['type']).strip().lower(),library['section_id'],
             *[server.get(key) for key in ('url','local_url','public_url')]]
    return hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()


def serializable_media(row):
    data = {key:row.get(key) for key in ('id','tmdb','imdb','tvdb','title','original_title','year','rating','added_at','release_date','people','genres','labels','tags','summary','countries','origin_country','production_countries')}
    if isinstance(data['added_at'],datetime):
        data['added_at'] = data['added_at'].isoformat()
    if isinstance(data['release_date'],(datetime,date)):
        data['release_date'] = data['release_date'].isoformat()
    if not data['id'] or not isinstance(data['title'],str):
        raise ValueError('collections.inventory_invalid')
    data['id'] = str(data['id'])
    return data


def inventory_failure(exc):
    if isinstance(exc,requests.exceptions.SSLError): return 'collections.inventory_tls_failed'
    if isinstance(exc,(requests.exceptions.ConnectionError,requests.exceptions.Timeout)): return 'collections.inventory_connection_failed'
    if isinstance(exc,requests.exceptions.InvalidURL): return 'collections.inventory_address_invalid'
    if isinstance(exc,sqlite3.Error): return 'collections.inventory_storage_failed'
    if getattr(getattr(exc,'response',None),'status_code',None) in (401,403): return 'collections.inventory_auth_failed'
    if isinstance(exc, requests.exceptions.JSONDecodeError): return 'collections.inventory_invalid'
    if isinstance(exc,ValueError) and str(exc) in ('collections.inventory_invalid','collections.inventory_address_invalid'): return str(exc)
    return 'collections.inventory_unavailable'


def inventory_connection_cause(exc):
    """Inspect wrapped network errors without exposing URLs, tokens or messages."""
    pending, seen = [exc], set()
    while pending and len(seen) < 64:
        error = pending.pop(0)
        if not isinstance(error, BaseException) or id(error) in seen:
            continue
        seen.add(id(error))
        if isinstance(error, requests.exceptions.SSLError): return 'tls'
        if isinstance(error, socket.gaierror): return 'dns'
        if isinstance(error, (requests.exceptions.Timeout, TimeoutError)): return 'timeout'
        if isinstance(error, OSError):
            code = getattr(error, 'winerror', None) or error.errno
            if code in (errno.ECONNREFUSED, 10061): return 'connection_refused'
            if code in (errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065): return 'network_unreachable'
            if code in (errno.ECONNRESET, errno.ECONNABORTED, 10053, 10054): return 'connection_reset'
        pending.extend([error.__cause__, error.__context__, getattr(error, 'reason', None), *error.args])
    return 'unknown'


def mark_inventory_failed(db,library_id,exc):
    now = stamp()
    db.execute("""INSERT INTO collection_inventory(library_id,started_at,finished_at,duration_seconds,state,last_error)
        VALUES(?,?,?,0,'error',?) ON CONFLICT(library_id) DO UPDATE
        SET started_at=excluded.started_at,finished_at=excluded.finished_at,duration_seconds=0,
            state='error',last_error=excluded.last_error""",(library_id,now,now,inventory_failure(exc)))


def refresh_library(db, server, library, adapter_factory=None, heartbeat=lambda:None):
    from core.collections_media import media_adapter
    import time
    started = time.monotonic()
    adapter = None
    db.execute("""INSERT INTO collection_inventory(library_id,started_at,state)
        VALUES(?,?,'running') ON CONFLICT(library_id) DO UPDATE
        SET started_at=excluded.started_at,state='running'""",(library['id'],stamp()))
    phase = 'connection'
    try:
        heartbeat()
        adapter = (adapter_factory or media_adapter)(server,library)
        adapter.heartbeat=heartbeat
        phase = 'read'
        rows = [serializable_media(row) for row in adapter.inventory()]
        identifiers = [row['id'] for row in rows]
        if len(set(identifiers))!=len(rows):
            raise ValueError('collections.inventory_invalid')
        generation = str(uuid.uuid4())
        finished = stamp()
        duration = round(time.monotonic()-started,3)
        # A failed/interrupted read never replaces the previous full snapshot.
        # Remote calls have all finished before starting this transaction.
        phase = 'persist'
        with db.transaction() as cur:
            cur.execute('DELETE FROM collection_inventory_media WHERE library_id=?',(library['id'],))
            cur.executemany('INSERT INTO collection_inventory_media(library_id,media_id,data_json) VALUES(?,?,?)',
                ((library['id'],row['id'],json.dumps(row,ensure_ascii=False)) for row in rows))
            cur.execute('DELETE FROM collection_inventory_audio WHERE library_id=?',(library['id'],))
            cur.execute('DELETE FROM collection_unavailable_media WHERE library_id=?',(library['id'],))
            cur.execute("""UPDATE collection_inventory SET generation=?,scope=?,completed_at=?,finished_at=?,
                duration_seconds=?,media_count=?,state='ready',last_error=NULL WHERE library_id=?""",
                (generation,scope_key(server,library),finished,finished,duration,len(rows),library['id']))
        return {'library_id':library['id'],'media_count':len(rows),'duration_seconds':duration}
    except Exception as exc:
        exc.inventory_stage = phase
        db.execute("""UPDATE collection_inventory SET state='error',last_error=?,
            finished_at=?,duration_seconds=? WHERE library_id=?""",
            (inventory_failure(exc),stamp(),round(time.monotonic()-started,3),library['id']))
        raise
    finally:
        if adapter is not None:
            adapter.close()


def inventory_status(db):
    return [dict(row) for row in db.query('''SELECT l.id AS library_id,l.name,s.name AS server_name,
        i.state,i.completed_at,i.finished_at,i.duration_seconds,i.media_count,i.last_error
        FROM libraries l JOIN servers s ON s.id=l.server_id
        LEFT JOIN collection_inventory i ON i.library_id=l.id
        WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
        AND LOWER(TRIM(l.type)) IN ('movie','movies','film','films','show','shows','series','tvshow','tvshows')
        ORDER BY s.id,l.id''')]


class LocalPlexIdentity:
    """IDs need no PlexAPI parsing; hydrate a selected item's methods on demand."""
    def __init__(self, server, section_id, row, movie):
        self._server=server;self._section_id=section_id;self._row=row;self._movie=movie;self._materialized=None
        self.ratingKey=int(row['id']);self.type='movie' if movie else 'show'
        self.title=row['title'];self.key='/library/metadata/'+str(row['id'])
        self.year=row.get('year');self.originalTitle=row.get('original_title')
        self.guids=[SimpleNamespace(id=provider+'://'+str(row[provider])) for provider in ('tmdb','imdb','tvdb') if row.get(provider)]

    def __getattr__(self, name):
        if self._materialized is None:
            from plexapi.video import Movie,Show
            attributes={'type':self.type,'ratingKey':str(self.ratingKey),'key':self.key,'title':self.title}
            if not self._movie:attributes.update(childCount='0',seasonCount='0')
            for key,field in (('year','year'),('originalTitle','original_title'),('originallyAvailableAt','release_date')):
                if self._row.get(field) is not None:
                    attributes[key]=str(self._row[field])[:10] if field=='release_date' else str(self._row[field])
            xml=Element('Video' if self._movie else 'Directory',attributes)
            for guid in self.guids:SubElement(xml,'Guid',{'id':guid.id})
            self._materialized=(Movie if self._movie else Show)(self._server,xml,
                initpath='/library/sections/'+str(self._section_id)+'/all')
        return getattr(self._materialized,name)


class CachedCollectionMedia:
    def __init__(self, db, server, library, adapter_factory=None):
        self.db,self.server,self.library = db,server,library
        self.adapter_factory = adapter_factory
        self.heartbeat = lambda:None
        self._remote = None
        self._rows = None
        self.generation = None
        self.supports_order = str(server['type']).strip().lower()=='plex'

    def remote(self):
        if self._remote is None:
            from core.collections_media import media_adapter
            self.heartbeat()
            self._remote = (self.adapter_factory or media_adapter)(self.server,self.library)
            self._remote.heartbeat = self.heartbeat
            self._remote.collection_db = self.db
            self._remote.collection_library_id = self.library['id']
        return self._remote

    def close(self):
        if self._remote is not None:
            self._remote.close()
        if getattr(self,'_new_collection_instances',None):
            from core.collections_control import queue_control
            with self.db.transaction() as cursor:
                for instance_id in self._new_collection_instances:queue_control(cursor,instance_id,priority=True)
            self._new_collection_instances.clear()

    def inventory(self):
        self.heartbeat()
        if self._rows is not None:
            return self._rows
        # A new library needs its first snapshot before any collection can use it.
        # The serial collection worker opts in; ordinary cache reads stay read-only.
        initial=self.db.query_one('SELECT generation FROM collection_inventory WHERE library_id=?',(self.library['id'],))
        if (not initial or not initial['generation']) and getattr(self.heartbeat,'bootstrap_inventory',False):
            refresh_library(self.db,self.server,self.library,adapter_factory=self.adapter_factory,heartbeat=self.heartbeat)
        # Read metadata and rows in one short transaction, so a concurrent refresh
        # cannot mix two generations. Fail closed on failed, old or moved sources.
        with self.db.transaction() as cur:
            meta = cur.execute('SELECT * FROM collection_inventory WHERE library_id=?',(self.library['id'],)).fetchone()
            if not meta or not meta['generation']:
                raise ValueError('collections.inventory_required')
            if (meta['last_error'] or meta['scope']!=scope_key(self.server,self.library)
                    or meta['completed_at']<stamp(utcnow()-timedelta(hours=36))):
                raise ValueError('collections.inventory_unavailable')
            rows = cur.execute('SELECT data_json FROM collection_inventory_media WHERE library_id=? ORDER BY media_id',
                (self.library['id'],)).fetchall()
            if len(rows)!=meta['media_count']:
                raise ValueError('collections.inventory_invalid')
            self.generation = meta['generation']
        unavailable={row['media_id'] for row in self.db.query(
            'SELECT media_id FROM collection_unavailable_media WHERE library_id=? AND generation=?',
            (self.library['id'],self.generation))}
        data = [json.loads(row['data_json']) for row in rows]
        data = [row for row in data if str(row['id']) not in unavailable]
        self._rows = self.restore_items(data)
        return self._rows

    def restore_items(self, data):
        """Construct identities only for the rows selected by a saved plan."""
        if self.supports_order:
            owner = self
            class ServerProxy:
                def __getattr__(self, name):
                    return getattr(owner.remote().plex,name)
            proxy = ServerProxy()
            movie_library = self.library['type'] in ('movie','movies','film','films')
            for row in data:
                row['item'] = LocalPlexIdentity(proxy,self.library['section_id'],row,movie_library)
        else:
            for row in data:
                row['item'] = {'Id':row['id'],'Name':row['title'],'PremiereDate':row.get('release_date')}
        return data

    def person_items(self, person, credits):
        def normalized(value):
            return ''.join(c for c in unicodedata.normalize('NFKD',str(value).casefold()) if not unicodedata.combining(c)).strip()
        names = {normalized(name) for name in [person['name'],*(person.get('aliases') or [])]}
        roles = ['actors'] if credits=='actors' else ['directors'] if credits=='directors' else ['actors','directors']
        return [row for row in self.inventory() if any(names & {normalized(name) for name in (row.get('people') or {}).get(role,[])} for role in roles)]

    def complete_person_items(self, person, credits):
        rows = {row['id']:row for row in self.person_items(person,credits)}
        if self.supports_order:
            # Plex's section scan may omit supporting cast. Its actor/director
            # index is complete and costs a filtered query, not a new scan.
            for row in self.remote().person_items(person,credits):
                rows[row['id']] = row
        return list(rows.values())

    def has_audio(self, row, language):
        if self.generation:
            cached = self.db.query_one('''SELECT available FROM collection_inventory_audio
                WHERE library_id=? AND generation=? AND media_id=? AND language=?''',
                (self.library['id'],self.generation,row['id'],language))
            if cached is not None: return bool(cached['available'])
        available = self.remote().has_audio(row,language)
        if self.generation:
            self.db.execute('INSERT OR REPLACE INTO collection_inventory_audio VALUES(?,?,?,?,?)',
                (self.library['id'],self.generation,row['id'],language,int(available)))
        return available

    def collection_members(self, record): return self.remote().collection_members(record)
    def sync(self, *args):
        from core.collections_publication import record_plan,finish_plan
        if args[3].get('sort')=='random' and not args[3].get('_order_seed'):
            args=(*args[:3],{**args[3],'_order_seed':utcnow().date().isoformat()},*args[4:])
        record_plan(self.db,*args[:4])
        remote=self.remote()
        warnings=remote.sync(*args)
        if args[0].get('instance_id') and args[0].get('id') and not args[0].get('remote_id'):
            if not hasattr(self,'_new_collection_instances'):self._new_collection_instances=set()
            self._new_collection_instances.add(args[0]['instance_id'])
        if args[0].get('id'):finish_plan(self.db,args[0]['id'],warnings)
        pending={'collections.membership_pending','collections.order_pending'} & set(warnings or [])
        changes=getattr(remote,'publication_changes',0)
        if pending and isinstance(changes,int) and changes>0:
            # Resume from actual server membership/order, only after progress.
            self.db.execute("UPDATE collection_instances SET requested='sync' WHERE id=? AND enabled=1 AND retired=0 AND requested IS NULL",
                (args[0]['instance_id'],))
        return warnings
    def delete(self, record): return self.remote().delete(record)
    @property
    def add_to_front(self):
        if not self.supports_order: raise AttributeError('add_to_front')
        return self.remote().add_to_front

    @property
    def remove_member(self):
        if not self.supports_order: raise AttributeError('remove_member')
        return self.remote().remove_member
