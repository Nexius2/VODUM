"""Administration of local lists used by Franchise."""
import os
from contextlib import contextmanager

import requests
from flask import jsonify, request, session
from requests.adapters import HTTPAdapter
from core.auth_principal import admin_required
from core import collections_lists_admin as lists
from core.collections_memoria_source import MemoriaSource
from core.collections_franchise_lists import definitions
from core.collections_repository import stamp,list_instances
from core.collections_list_metadata import search_media
from secret_store import decrypt_secret
from web.helpers import get_db


@contextmanager
def metadata_source(db):
    row = db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
    key = decrypt_secret(row['secret_tmdb']) if row and row['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
    language = request.args.get('language',session.get('lang','fr'))
    if language not in ('fr','en','de','es','it'):language='fr'
    source = MemoriaSource(key,language)
    source.http.mount('https://',HTTPAdapter(max_retries=0))
    original_get = source.http.get
    source.http.get = lambda *args,**kwargs: original_get(*args,**{**kwargs,'timeout':(3,6)})
    try:yield source
    finally:source.close()


def register(app, failure, payload):
    def failed(exc):
        if isinstance(exc,requests.RequestException):
            return jsonify(ok=False,error='collections.lists_metadata_unavailable'),502
        return failure(exc)

    @app.get('/api/collections/lists')
    @admin_required
    def collection_lists_catalog():
        return jsonify(ok=True,lists=lists.catalog(get_db()))

    @app.post('/api/collections/lists')
    @admin_required
    def collection_lists_create():
        try:
            db=get_db();key=lists.create_list(db,payload())
            return jsonify(ok=True,id=key,definitions=definitions(db))
        except (ValueError,TypeError) as exc:return failed(exc)

    @app.get('/api/collections/lists/<key>')
    @admin_required
    def collection_lists_contents(key):
        try:return jsonify(ok=True,list=lists.contents(get_db(),key))
        except ValueError as exc:return failed(exc)

    @app.post('/api/collections/lists/<key>')
    @admin_required
    def collection_lists_update(key):
        try:
            db=get_db();lists.update_list(db,key,payload())
            return jsonify(ok=True,definitions=definitions(db))
        except (ValueError,TypeError) as exc:return failed(exc)

    @app.get('/api/collections/lists/<key>/links')
    @admin_required
    def collection_list_link_targets(key):
        try:return jsonify(ok=True,targets=lists.link_targets(get_db(),key))
        except (ValueError,TypeError) as exc:return failed(exc)

    @app.post('/api/collections/lists/<key>/links')
    @admin_required
    def collection_list_links_update(key):
        try:
            db=get_db();lists.set_link(db,key,payload())
            return jsonify(ok=True,definitions=definitions(db),instances=list_instances(db))
        except (ValueError,TypeError) as exc:return failed(exc)

    @app.post('/api/collections/lists/<key>/order')
    @admin_required
    def collection_list_order_update(key):
        try:
            db=get_db();lists.set_order(db,key,payload())
            return jsonify(ok=True)
        except (ValueError,TypeError) as exc:return failed(exc)

    @app.post('/api/collections/lists/<key>/items')
    @admin_required
    def collection_list_items_update(key):
        try:
            db=get_db();data=payload();lists.require_list(db,key)
            provider,kind,identifier=lists.identity(data)
            metadata=None
            if data.get('action')=='add':
                with metadata_source(db) as source:
                    metadata=lists.resolve_media(source,provider,kind,identifier)
            lists.update_item(db,key,data,metadata)
            return jsonify(ok=True)
        except (ValueError,TypeError,RuntimeError,requests.RequestException) as exc:return failed(exc)

    @app.post('/api/collections/lists/<key>/resolve')
    @admin_required
    def collection_list_item_resolve(key):
        try:
            db=get_db();lists.require_list(db,key);data=payload()
            provider,kind,identifier=lists.identity(data)
            row=db.query_one('SELECT * FROM franchise_list_items WHERE list_id=? AND provider=? AND media_type=? AND external_id=?',(key,provider,kind,identifier))
            if row is None:raise ValueError('collections.lists_not_found')
            if row['metadata_state']=='resolved' and row['poster_path'] and not data.get('retry'):
                return jsonify(ok=True,media=dict(row))
            try:
                with metadata_source(db) as source:
                    media=lists.resolve_media(source,provider,kind,identifier)
            except ValueError as exc:
                if str(exc)!='collections.lists_identity_failed':raise
                # An absent mapping is a result for this entry, not a batch failure.
                media={**dict(row),'metadata_state':'not_found','metadata_error':'collections.lists_metadata_missing'}
                db.execute("""UPDATE franchise_list_items SET metadata_state='not_found',metadata_error=?,metadata_checked_at=?
                    WHERE list_id=? AND provider=? AND media_type=? AND external_id=?""",
                    ('collections.lists_metadata_missing',stamp(),key,provider,kind,identifier))
                return jsonify(ok=True,media=media)
            db.execute("""UPDATE franchise_list_items SET title=CASE WHEN title IS NULL OR title='' THEN ? ELSE title END,
                year=COALESCE(NULLIF(year,''),?),poster_path=COALESCE(?,poster_path),metadata_state=?,metadata_error=NULL,metadata_checked_at=?
                WHERE list_id=? AND provider=? AND media_type=? AND external_id=?""",
                (media['title'],media['year'],media.get('poster_path'),media.get('metadata_state','resolved' if media.get('poster_path') else 'partial'),stamp(),key,provider,kind,identifier))
            saved=db.query_one('SELECT * FROM franchise_list_items WHERE list_id=? AND provider=? AND media_type=? AND external_id=?',(key,provider,kind,identifier))
            return jsonify(ok=True,media=dict(saved))
        except (ValueError,TypeError,RuntimeError,requests.RequestException) as exc:return failed(exc)

    @app.get('/api/collections/lists/search')
    @admin_required
    def collection_list_media_search():
        try:
            query=request.args.get('q','').strip();kind=request.args.get('type','all')
            if not 2<=len(query)<=200 or kind not in ('all','movie','tv'):
                raise ValueError('collections.search_query_required')
            with metadata_source(get_db()) as source:
                rows=search_media(source,query,kind)
            return jsonify(ok=True,results=rows)
        except (ValueError,TypeError,RuntimeError,requests.RequestException) as exc:return failed(exc)
