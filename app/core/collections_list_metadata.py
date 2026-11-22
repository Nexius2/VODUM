"""Exact provider identities for list metadata; never match by approximate title."""
import json
import re
from pathlib import Path
from requests import RequestException, HTTPError
from core.collections_portraits import portrait_path

_SUPPLEMENTS = json.loads((Path(__file__).resolve().parents[1] / 'data/franchise_supplements.json').read_text(encoding='utf-8'))
_BUNDLED = {row['imdb_id']: row for rows in _SUPPLEMENTS['universes'].values() for row in rows}
_MOVIES = ('movie', 'short', 'video', 'tvMovie', 'tvShort', 'tvSpecial')
_SERIES = ('tvSeries', 'tvMiniSeries')


def bundled_title(provider, identifier, kind):
    row = _BUNDLED.get(identifier) if provider == 'imdb' else None
    if row and row.get('type') in (_SERIES if kind == 'tv' else _MOVIES):
        return row.get('title')
    return None


def imdb_metadata(source, identifier, kind=None):
    if not re.fullmatch(r'tt[0-9]+', identifier):
        raise ValueError('collections.invalid_configuration')
    fallback = bundled_title('imdb', identifier, kind or 'movie')
    try:
        response = source.http.post('https://api.graphql.imdb.com/',
            headers={'Content-Type':'application/json', 'x-imdb-client-name':'imdb-web-next'},
            json={'query': 'query($id: ID!) { title(id: $id) { id titleText { text } titleType { id } releaseYear { year } primaryImage { url } } }',
                  'variables': {'id': identifier}}, timeout=(3,6))
        try:
            response.raise_for_status()
            payload = response.json()
        finally:
            response.close()
        node = (payload.get('data') or {}).get('title') if isinstance(payload, dict) and not payload.get('errors') else None
        if not isinstance(node, dict) or node.get('id') != identifier:
            raise ValueError('collections.lists_identity_failed')
        title = (node.get('titleText') or {}).get('text')
        title_type = (node.get('titleType') or {}).get('id')
        actual_kind = 'tv' if title_type in _SERIES else 'movie' if title_type in _MOVIES else None
        if not actual_kind or (kind and kind != actual_kind) or not isinstance(title, str) or not title.strip():
            raise ValueError('collections.lists_identity_failed')
        year = (node.get('releaseYear') or {}).get('year')
        image = (node.get('primaryImage') or {}).get('url')
        path = 'imdb:' + image[len('https://m.media-amazon.com'):] if isinstance(image, str) and image.startswith('https://m.media-amazon.com/images/M/') else None
        return {'provider':'imdb', 'media_type':actual_kind, 'external_id':identifier,
                'title':title.strip(), 'year':str(year) if type(year) is int else '', 'poster_path':portrait_path(path)}
    except (RequestException, ValueError, TypeError):
        if fallback:
            return {'provider':'imdb', 'media_type':kind or 'movie', 'external_id':identifier,
                    'title':fallback, 'year':'', 'poster_path':None, 'metadata_state':'partial'}
        raise ValueError('collections.lists_identity_failed') from None


def search_media(source, query, kind='all'):
    # Numeric IDs require a provider, since TMDB and TVDB numbers overlap.
    match = re.fullmatch(r'(imdb|tmdb|tvdb):(?:(movie|tv):)?(tt[0-9]+|[1-9][0-9]*)', query, re.I)
    provider, explicit, identifier = match.groups() if match else (('imdb', None, query) if re.fullmatch(r'tt[0-9]+', query) else (None,None,None))
    if provider:
        provider=provider.lower(); explicit=explicit.lower() if explicit else None
        identifier=identifier.lower()
        if not re.fullmatch(r'tt[0-9]+' if provider=='imdb' else r'[1-9][0-9]*', identifier):
            raise ValueError('collections.search_query_required')
        allowed = [k for k in ('movie','tv') if kind in ('all',k) and (not explicit or explicit==k)]
        if provider=='tvdb':allowed=[k for k in allowed if k=='tv']
        if provider=='tmdb':
            candidates=[]
            for media_kind in allowed:
                try: row=source.tmdb('/'+media_kind+'/'+identifier)
                except HTTPError as exc:
                    if exc.response is not None and exc.response.status_code==404:continue
                    raise
                if isinstance(row,dict) and row.get('id')==int(identifier):
                    candidates.append({**row,'media_type':media_kind})
        else:
            data=source.tmdb('/find/'+identifier,external_source=provider+'_id')
            candidates=[{**row,'media_type':media_kind} for media_kind in allowed
                        for row in data.get(media_kind+'_results',[]) if isinstance(row,dict)]
            if not candidates and provider=='imdb':
                try:
                    row=imdb_metadata(source,identifier,explicit or (kind if kind!='all' else None))
                    return [row] if row['media_type'] in allowed else []
                except ValueError:return []
    else:
        data=source.tmdb('/search/'+('multi' if kind=='all' else kind),query=query,include_adult='false')
        candidates=[{**row,'media_type':row.get('media_type') if kind=='all' else kind}
                    for row in data.get('results',[]) if isinstance(row,dict)]
    return [{'provider':'tmdb','media_type':row['media_type'],'external_id':str(row['id']),
             'title':row.get('title') or row.get('name'),
             'year':str(row.get('release_date') or row.get('first_air_date') or '')[:4],
             'poster_path':portrait_path(row.get('poster_path'))}
            for row in candidates if row.get('media_type') in ('movie','tv')
            and type(row.get('id')) is int and row['id']>0 and (row.get('title') or row.get('name'))][:20]
