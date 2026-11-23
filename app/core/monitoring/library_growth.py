"""Aggregate recent films and episodes without scanning media from the web request."""

from datetime import datetime, timedelta, timezone

from core.server_page_queries import LIBRARY_TYPE_SQL

PERIODS = (7, 30, 365)
PAGE_SIZE = 1000
SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_library_growth (
    library_id INTEGER PRIMARY KEY REFERENCES libraries(id) ON DELETE CASCADE,
    measured_at TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    last_attempt_at TEXT,
    last_error TEXT
)
"""

GROWTH_LIBRARIES = f"""
    LOWER(TRIM(s.type)) IN ('plex', 'jellyfin')
      AND {LIBRARY_TYPE_SQL} IN ('movie', 'shows')
"""


def _file_size(values):
    sizes = [int(str(value)) if str(value).isdigit() else 0 for value in values]
    return (sum(sizes), bool(sizes) and all(sizes))


def _plex_items(adapter, library, _now):
    libtype = 'movie' if library['normalized_type'] == 'movie' else 'episode'
    offset = 0
    while True:
        adapter.heartbeat()
        items = adapter.section.search(
            libtype=libtype, filters={f'{libtype}.addedAt>>': '366d'},
            container_start=offset, container_size=PAGE_SIZE, maxresults=PAGE_SIZE,
        )
        total = getattr(items, 'totalSize', None)
        if not items:
            if isinstance(total, int) and offset < total:
                raise ValueError('Incomplete Plex library growth scan')
            return
        for item in items:
            data = vars(item)['_data']
            added = datetime.fromtimestamp(int(data.attrib['addedAt']), tz=timezone.utc)
            yield str(item.ratingKey), added, _file_size(part.get('size') for part in data.findall('Media/Part'))
        offset += len(items)
        if (isinstance(total, int) and offset >= total) or (total is None and len(items) < PAGE_SIZE):
            return



def _jellyfin_items(adapter, library, now):
    item_type = 'Movie' if library['normalized_type'] == 'movie' else 'Episode'
    params = dict(ParentId=library['section_id'], Recursive='true', IncludeItemTypes=item_type,
                  Fields='DateCreated,MediaSources', SortBy='DateCreated', SortOrder='Descending',
                  Limit=PAGE_SIZE)
    cutoff = now - timedelta(days=max(PERIODS))
    offset = 0
    while True:
        adapter.heartbeat()
        result = adapter.request('GET', '/Items', params={**params, 'StartIndex': offset})
        items = result['Items']
        total = result['TotalRecordCount']
        if not isinstance(items, list) or type(total) is not int or total < 0:
            raise ValueError('Invalid Jellyfin library growth page')
        if not items and offset < total:
            raise ValueError('Incomplete Jellyfin library growth scan')
        for item in items:
            added = datetime.fromisoformat(item['DateCreated'].replace('Z', '+00:00'))
            if added.tzinfo is None:
                added = added.replace(tzinfo=timezone.utc)
            if added < cutoff:
                return
            yield str(item['Id']), added, _file_size(source.get('Size') for source in item.get('MediaSources') or [])
        offset += len(items)
        if offset >= total:
            return


def scan_growth(server, library, now, heartbeat):
    from core.collections_media import media_adapter

    is_plex = server['type'].strip().lower() == 'plex'
    adapter = media_adapter(server, library)
    adapter.heartbeat = heartbeat
    try:
        items = _plex_items if is_plex else _jellyfin_items
        totals = {str(days): {'items': 0, 'bytes': 0, 'missing': 0} for days in PERIODS}
        cutoffs = {str(days): now - timedelta(days=days) for days in PERIODS}
        seen = set()
        for item_id, added, (size, complete) in items(adapter, library, now):
            heartbeat()
            if item_id in seen:
                raise ValueError('Duplicate item in library growth scan')
            seen.add(item_id)
            for period, cutoff in cutoffs.items():
                if cutoff <= added <= now:
                    totals[period]['items'] += 1
                    totals[period]['bytes'] += size
                    totals[period]['missing'] += int(not complete)
        return totals
    finally:
        adapter.close()


