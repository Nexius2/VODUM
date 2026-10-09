"""Decorative posters from existing monitoring and disk caches only."""
import json
import os
import tempfile
from urllib.parse import urlsplit, parse_qs
from flask import url_for
from core.aggregate_cache import peek_aggregate
from core.monitoring.artwork_cache import artwork_cache_key, read_artwork_cache
from db_manager import isolated_read_operation
from core.monitoring import artwork_cache


def remember_backdrop_candidates(result):
    """Persist only public history IDs; survives restart and multiple workers."""
    payload = {kind: [{'hist_id': int(row['hist_id']), 'cache_key': _displayed_poster_key(row)} for row in result.get(key, [])[:4]
                      if row.get('hist_id')]
               for kind, key in (('top-movies', 'top_movies_30d'), ('top-series', 'top_content_30d'))}
    temporary = None
    try:
        directory = artwork_cache.ARTWORK_CACHE_DIR
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='portal-backdrop-', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle)
        os.replace(temporary, directory / 'portal-backdrop.json')
    except OSError:
        pass
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _saved_candidates():
    try:
        with (artwork_cache.ARTWORK_CACHE_DIR / 'portal-backdrop.json').open(encoding='utf-8') as handle:
            data = json.loads(handle.read(8192))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _poster_key(row):
    try:
        ref = json.loads(row.get('poster_ref_json') or '{}')
    except (ValueError, TypeError):
        return None
    if not isinstance(ref, dict):
        return None
    provider = str(row.get('provider') or '').lower()
    if provider == 'plex' and ref.get('path'):
        return artwork_cache_key('plex', row['server_id'], ref['path'])
    if provider == 'jellyfin' and ref.get('item_id'):
        return artwork_cache_key('jellyfin', row['server_id'], ref['item_id'],
                                 ref.get('image_type') or 'Primary', None, '120', '90')
    return None


def _displayed_poster_key(row):
    """Use the resolved poster URL actually rendered by Monitoring."""
    query = parse_qs(urlsplit(row.get('poster_url') or '').query)
    if query.get('path'):
        return artwork_cache_key('plex', row['server_id'], query['path'][0])
    if query.get('item_id'):
        return artwork_cache_key('jellyfin', row['server_id'], query['item_id'][0],
                                 query.get('image_type', ['Primary'])[0], None, '120', '90')
    return None


@isolated_read_operation
def cached_request_poster(db, history_id, libraries):
    row = db.query_one('''SELECT h.server_id, s.type AS provider, h.poster_ref_json,
        h.library_section_id FROM media_session_history h
        JOIN servers s ON s.id = h.server_id WHERE h.id = ?''', (history_id,))
    if not row:
        return None
    row = dict(row)
    if row.get('library_section_id') in (None, ''):
        return None
    if not any(int(library['server_id']) == int(row['server_id']) and
               str(library['section_id']) == str(row['library_section_id'])
               for library in libraries):
        return None
    key = _poster_key(row)
    saved = _saved_candidates()
    for kind in ('top-movies', 'top-series'):
        for candidate in saved.get(kind, [])[:4]:
            if isinstance(candidate, dict) and candidate.get('hist_id') == history_id:
                selected_key = candidate.get('cache_key')
                if isinstance(selected_key, str) and len(selected_key) == 64 and all(char in '0123456789abcdef' for char in selected_key):
                    key = selected_key
    return read_artwork_cache(key, allow_stale=True) if key else None


@isolated_read_operation
def request_backdrop_posters(db, libraries):
    if not libraries:
        return []
    groups = []
    seen = set()
    seen_images = set()
    saved = _saved_candidates()
    for kind in ('top-movies', 'top-series'):
        posters = []
        rows = saved[kind] if kind in saved else (peek_aggregate(f'monitoring:overview:{kind}-30d') or [])
        found = 0
        for row in rows[:4]:
            if not isinstance(row, dict):
                continue
            history_id = row.get('hist_id')
            if not isinstance(history_id, int) or history_id <= 0 or history_id in seen:
                continue
            seen.add(history_id)
            try:
                cached = cached_request_poster(db, history_id, libraries)
            except OSError:
                cached = None
            if cached and str(cached['path']) not in seen_images:
                seen_images.add(str(cached['path']))
                posters.append(url_for('portal_request_backdrop_poster', history_id=int(history_id)))
                found += 1
                if found == 4:
                    break
        groups.append(posters)
    return [group[index] for index in range(4) for group in groups if index < len(group)]
