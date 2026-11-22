"""Shared inventory matching for anime rankings."""

from collections import defaultdict
import re
import unicodedata

from requests import Session

from core.collections_streaming_source import StreamingSource


def title_key(value):
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', value or '').casefold()))


class AnimeChartSource(StreamingSource):
    match_resolved_inventory_only = True
    partial = False

    def __init__(self, _key, language, *, session_factory=Session):
        self.language = language
        self.db = None
        self.heartbeat = lambda: None
        self.diagnostics = []
        self.http = session_factory()

    def match_inventory(self, candidates, inventory):
        by_title_year = defaultdict(set)
        for row in inventory:
            self.heartbeat()
            year = str(row.get('year') or row.get('release_date') or '')[:4]
            if year.isdecimal() and len(year) == 4:
                for name in (row.get('title'), row.get('original_title')):
                    if key := title_key(name):
                        by_title_year[key, year].add(str(row['id']))

        matches = {}
        by_local_id = defaultdict(set)
        for candidate in candidates:
            self.heartbeat()
            local_ids = set()
            for title in candidate['titles']:
                local_ids.update(by_title_year[title_key(title), candidate['year']])
            if len(local_ids) == 1:
                local_id = next(iter(local_ids))
                matches[candidate['id']] = [local_id]
                by_local_id[local_id].add(candidate['id'])
        return {identifier: ids for identifier, ids in matches.items() if len(by_local_id[ids[0]]) == 1}
