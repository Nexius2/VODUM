"""Discover public AniList rankings for Plex and Jellyfin collections."""

import json

from requests import RequestException

from core.collections_anime import AnimeChartSource
from core.collections_anime_catalog import CHARTS, anime_collection_name
from core.collections_media import media_adapter
from core.collections_streaming import run_streaming_country


API_URL = 'https://graphql.anilist.co'
PAGE_SIZE = 50
CHART_LIMIT = 500
TV_FORMATS = ('TV', 'TV_SHORT')
SERIES_FORMATS = (*TV_FORMATS, 'ONA', 'OVA')
CHART_FORMATS = {'tv': TV_FORMATS, 'movie': ('MOVIE',), 'bypopularity': (*SERIES_FORMATS, 'MOVIE')}
RANKING_QUERY = """query ($page: Int!, $pageSize: Int!, $formats: [MediaFormat!]!, $sort: [MediaSort!]!) {
  Page(page: $page, perPage: $pageSize) {
    pageInfo { hasNextPage }
    media(type: ANIME, isAdult: false, format_in: $formats, sort: $sort) {
      id
      format
      title { romaji english native }
      synonyms
      startDate { year }
    }
  }
}"""


class AniListSource(AnimeChartSource):
    def discover(self, chart, media_type):
        library_type = 'movie' if media_type == 'movie' else 'shows'
        if library_type not in CHARTS.get(chart, ()):
            raise ValueError('collections.anilist_invalid_chart')

        rows = self.cached(['anilist-ranking-v1', chart], 6, lambda: self.chart(chart))
        formats = ('MOVIE',) if media_type == 'movie' else SERIES_FORMATS
        candidates = [
            {**row, 'sources': ['anilist'], 'ranks_by_source': {'anilist': row['rank']},
             'source_kinds': {'anilist': 'anilist_chart'}, 'buzz_score': CHART_LIMIT + 1 - row['rank'],
             'tmdb_id': None}
            for row in rows if row['format'] in formats
        ]
        if not candidates:
            raise ValueError('collections.anilist_source_invalid')
        self.diagnostics = [{
            'id': 'anilist', 'name': anime_collection_name('anilist', chart, self.language, media_type),
            'state': 'success', 'count': len(candidates), 'source_kind': 'anilist_chart',
            'url': 'https://anilist.co/search/anime',
        }]
        return candidates

    def chart(self, chart):
        formats = CHART_FORMATS[chart]
        order = 'POPULARITY_DESC' if chart == 'bypopularity' else 'SCORE_DESC'
        rows = []
        seen = set()
        for page in range(1, CHART_LIMIT // PAGE_SIZE + 1):
            data = self.page(page, formats, order)
            try:
                media = data['media']
                has_next = data['pageInfo']['hasNextPage']
                if (not isinstance(media, list) or not media or len(media) > PAGE_SIZE
                        or type(has_next) is not bool or has_next and len(media) != PAGE_SIZE):
                    raise ValueError()
                for node in media:
                    identifier, media_format = node['id'], node['format']
                    if type(identifier) is not int or identifier <= 0 or identifier in seen or media_format not in formats:
                        raise ValueError()
                    names = node['title']
                    synonyms = node['synonyms'] or []
                    if not isinstance(synonyms, list):
                        raise ValueError()
                    titles = [
                        name for name in (names['romaji'], names['english'], names['native'], *synonyms)
                        if isinstance(name, str) and name.strip()
                    ]
                    if not titles:
                        raise ValueError()
                    seen.add(identifier)
                    rows.append({
                        'id': identifier, 'title': titles[0], 'titles': titles,
                        'year': str((node['startDate'] or {}).get('year') or ''),
                        'format': media_format, 'rank': len(rows) + 1,
                    })
            except (KeyError, ValueError, TypeError, AttributeError):
                raise ValueError('collections.anilist_source_invalid') from None
            if not has_next:
                break
        return rows

    def page(self, page, formats, order):
        self.heartbeat()
        variables = {'page': page, 'pageSize': PAGE_SIZE, 'formats': formats, 'sort': [order, 'ID']}
        try:
            response = self.http.post(
                API_URL, json={'query': RANKING_QUERY, 'variables': variables},
                timeout=(10, 30), allow_redirects=False,
            )
        except RequestException:
            raise ValueError('collections.anilist_source_unavailable') from None
        if response.status_code != 200:
            raise ValueError('collections.anilist_source_unavailable')
        try:
            payload = response.json()
            if payload.get('errors'):
                raise ValueError()
            return payload['data']['Page']
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError('collections.anilist_source_invalid') from None


def run_anilist(db, instance, *, kind='sync', heartbeat=lambda: None,
                source_factory=AniListSource, adapter_factory=media_adapter):
    config = json.loads(instance['config_json'])
    chart = config['anilist_chart']
    return run_streaming_country(
        db, {**instance, 'config_json': json.dumps({**config, 'country': chart})},
        kind=kind, heartbeat=heartbeat, source_factory=source_factory, adapter_factory=adapter_factory,
        title_override=instance['name'], poster_key_override='anilist_' + chart, uses_tmdb=False,
    )
