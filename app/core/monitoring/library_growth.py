"""Aggregate library size and recent additions without scanning media from the web request.

"Media growth" is the net change of the library's total file size between two
successful scans. It must not be derived from item addition dates: Plex and
Jellyfin reset those dates when media is re-added (rescan, path or agent
change, library rebuild), which would report the whole re-added content as new.
"""

from datetime import datetime, timedelta, timezone

from core.server_page_queries import LIBRARY_TYPE_SQL

PERIODS = (7, 30, 365)
PAGE_SIZE = 1000
# A daily scan rarely runs exactly 24 h apart; accept a baseline this much
# newer than the period start so "last 7 days" still uses the scan of D-7.
BASELINE_TOLERANCE = timedelta(hours=6)
SIZE_HISTORY_RETENTION_DAYS = max(PERIODS) + 35
HISTORY_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_library_growth (
    library_id INTEGER PRIMARY KEY REFERENCES libraries(id) ON DELETE CASCADE,
    measured_at TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    last_attempt_at TEXT,
    last_error TEXT
)
"""

SIZE_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_library_size_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    measured_at TEXT NOT NULL,
    total_items INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0
)
"""
SIZE_HISTORY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_library_size_history_library_time
ON monitoring_library_size_history(library_id, measured_at)
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
        # The whole section is read: the total size is needed for net growth.
        items = adapter.section.search(
            libtype=libtype, container_start=offset, container_size=PAGE_SIZE, maxresults=PAGE_SIZE,
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



def _jellyfin_items(adapter, library, _now):
    item_type = 'Movie' if library['normalized_type'] == 'movie' else 'Episode'
    params = dict(ParentId=library['section_id'], Recursive='true', IncludeItemTypes=item_type,
                  # Oldest first: media added during a long scan land on the last
                  # page instead of shifting every page (duplicates, scan failure).
                  Fields='DateCreated,MediaSources', SortBy='DateCreated,SortName', SortOrder='Ascending',
                  Limit=PAGE_SIZE)
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
        library_total = {'items': 0, 'bytes': 0, 'missing': 0}
        cutoffs = {str(days): now - timedelta(days=days) for days in PERIODS}
        seen = set()
        for item_id, added, (size, complete) in items(adapter, library, now):
            heartbeat()
            if item_id in seen:
                raise ValueError('Duplicate item in library growth scan')
            seen.add(item_id)
            library_total['items'] += 1
            library_total['bytes'] += size
            library_total['missing'] += int(not complete)
            for period, cutoff in cutoffs.items():
                if cutoff <= added <= now:
                    totals[period]['items'] += 1
                    totals[period]['bytes'] += size
                    totals[period]['missing'] += int(not complete)
        totals['library'] = library_total
        return totals
    finally:
        adapter.close()


def _parse_history_time(value):
    return datetime.strptime(value, HISTORY_TIME_FORMAT).replace(tzinfo=timezone.utc)


def net_growth(history, now, days):
    """Return the net size change over `days` from scan snapshots.

    `history` holds (measured_at, total_bytes, missing[, total_items]) tuples
    of successful scans, the current one included, measured_at as
    HISTORY_TIME_FORMAT UTC. With item totals, the net item change is returned
    too, so re-added media are not counted as new.
    The baseline is the latest scan at or before the period start. Without one,
    the oldest earlier scan is used and the result is flagged partial. Without
    any earlier scan, no growth can be computed yet.
    """
    rows = sorted(
        (_parse_history_time(row[0]), int(row[1]), int(row[2] or 0),
         int(row[3]) if len(row) > 3 and row[3] is not None else None)
        for row in history
    )
    current = [row for row in rows if row[0] <= now]
    if len(current) < 2:
        return None
    current_at, current_bytes, current_missing, current_items = current[-1]
    earlier = current[:-1]
    start = now - timedelta(days=days)
    eligible = [row for row in earlier if row[0] <= start + BASELINE_TOLERANCE]
    baseline = eligible[-1] if eligible else earlier[0]
    baseline_at, baseline_bytes, baseline_missing, baseline_items = baseline
    result = {
        'net_bytes': current_bytes - baseline_bytes,
        'net_since': baseline_at.strftime('%Y-%m-%d'),
        'net_partial': not eligible,
        'net_incomplete': bool(current_missing or baseline_missing),
    }
    if current_items is not None and baseline_items is not None:
        result['net_items'] = current_items - baseline_items
    return result
