"""Publish MyAnimeList rankings against the selected library inventory."""

import json

from requests import RequestException, Session

from core.collections_media import media_adapter
from core.collections_anime import AnimeChartSource
from core.collections_anime_catalog import CHARTS, anime_collection_name
from core.collections_streaming import run_streaming_country
from secret_store import SecretDecryptionError, decrypt_secret


RANKING_URL = 'https://api.myanimelist.net/v2/anime/ranking'
CHART_LIMIT = 500
SERIES_TYPES = {'tv', 'ona', 'ova'}


class MyAnimeListSource(AnimeChartSource):
    def __init__(self, key, language):
        super().__init__(key, language, session_factory=Session)

    def discover(self, chart, media_type):
        library_type = 'movie' if media_type == 'movie' else 'shows'
        if library_type not in CHARTS.get(chart, ()):
            raise ValueError('collections.myanimelist_invalid_chart')
        settings = self.db.query_one('SELECT secret_myanimelist FROM collection_settings WHERE id=1')
        if not settings or not settings['secret_myanimelist']:
            raise ValueError('collections.myanimelist_key_required')
        try:
            client_id = decrypt_secret(settings['secret_myanimelist'])
        except SecretDecryptionError:
            raise ValueError('collections.secret_store_unavailable') from None
        rows = self.cached(['myanimelist-ranking-v1', chart], 6, lambda: self.chart(chart, client_id))
        allowed_types = {'movie'} if media_type == 'movie' else SERIES_TYPES
        candidates = [
            {**row, 'sources': ['myanimelist'], 'ranks_by_source': {'myanimelist': row['rank']},
             'source_kinds': {'myanimelist': 'myanimelist_chart'}, 'buzz_score': CHART_LIMIT + 1 - row['rank'],
             'tmdb_id': None}
            for row in rows if row['media_type'] in allowed_types
        ]
        if not candidates:
            raise ValueError('collections.myanimelist_source_invalid')
        self.diagnostics = [{
            'id': 'myanimelist', 'name': anime_collection_name('myanimelist', chart, self.language, media_type),
            'state': 'success', 'count': len(candidates), 'source_kind': 'myanimelist_chart',
            'url': 'https://myanimelist.net/topanime.php?type=' + chart,
        }]
        return candidates

    def chart(self, chart, client_id):
        self.heartbeat()
        try:
            response = self.http.get(
                RANKING_URL, headers={'X-MAL-CLIENT-ID': client_id}, allow_redirects=False,
                params={'ranking_type': chart, 'limit': CHART_LIMIT, 'nsfw': 'false',
                        'fields': 'alternative_titles,start_date,media_type'},
                timeout=(10, 30),
            )
            if response.status_code != 200:
                raise ValueError('collections.myanimelist_source_unavailable')
        except RequestException:
            raise ValueError('collections.myanimelist_source_unavailable') from None

        try:
            rows = []
            identifiers = set()
            data = response.json()['data']
            if not isinstance(data, list) or not data:
                raise ValueError()
            for rank, entry in enumerate(data, 1):
                node = entry['node']
                identifier, title, media_type = node['id'], node['title'], node['media_type']
                if (type(identifier) is not int or identifier <= 0 or identifier in identifiers
                        or not isinstance(title, str) or not title.strip() or not isinstance(media_type, str)):
                    raise ValueError()
                identifiers.add(identifier)
                alternatives = node.get('alternative_titles') or {}
                synonyms = alternatives.get('synonyms') or []
                if not isinstance(synonyms, list):
                    raise ValueError()
                titles = [title, alternatives.get('en'), alternatives.get('ja'), *synonyms]
                rows.append({
                    'id': identifier, 'title': title, 'year': str(node.get('start_date') or '')[:4],
                    'titles': [name for name in titles if isinstance(name, str) and name.strip()],
                    'media_type': media_type, 'rank': rank,
                })
            return rows
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError('collections.myanimelist_source_invalid') from None


def run_myanimelist(db, instance, *, kind='sync', heartbeat=lambda: None,
                    source_factory=MyAnimeListSource, adapter_factory=media_adapter):
    config = json.loads(instance['config_json'])
    chart = config['myanimelist_chart']
    return run_streaming_country(
        db, {**instance, 'config_json': json.dumps({**config, 'country': chart})},
        kind=kind, heartbeat=heartbeat, source_factory=source_factory, adapter_factory=adapter_factory,
        title_override=instance['name'], poster_key_override='myanimelist_' + chart, uses_tmdb=False,
    )
