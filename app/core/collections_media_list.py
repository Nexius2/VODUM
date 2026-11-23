"""Publish exactly one local media list through the shared collection engine."""
import json
from core.collections_universes import UniverseLists
from core.collections_streaming_source import StreamingSource
from core.collections_streaming import run_streaming_country
from core.collections_media import media_adapter
from core.collections_universes_catalog import UNIVERSES


class MediaListSource(UniverseLists, StreamingSource):
    def discover(self, country, media_type):
        definition=self.db.query_one('SELECT name,enabled FROM franchise_lists WHERE id=?',(self.list_id,))
        if definition is None or not definition['enabled']:
            raise ValueError('collections.media_list_required')
        self.partial=False
        self.diagnostics=[]
        _,_,rows=self.universe_members(self.list_id,media_type)
        self.diagnostics.append({'id':'media_list','name':definition['name'],
            'state':'warning' if self.partial else 'success','count':len(rows),'source_kind':'media_list'})
        # Canonical list membership is already deduplicated by typed TMDB ID.
        for index,row in enumerate(rows,1):
            row.update(rank=index,sources=['media_list'],source_kinds={'media_list':'media_list'},
                       ranks_by_source={'media_list':index})
        return rows


def run_media_list(db, instance, *, kind='sync', heartbeat=lambda:None,
                   source_factory=MediaListSource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    definition=db.query_one('SELECT name,enabled FROM franchise_lists WHERE id=?',(config['media_list'],))
    # Cleanup must remain possible even if the source list no longer exists.
    if kind not in ('cleanup','delete','expire') and (definition is None or not definition['enabled']):
        raise ValueError('collections.media_list_required')
    def source(key,language):
        result=source_factory(key,language)
        result.list_id=config['media_list']
        return result
    return run_streaming_country(db,{**instance,'config_json':json.dumps({**config,'country':'media_list'})},
        kind=kind,heartbeat=heartbeat,source_factory=source,adapter_factory=adapter_factory,
        title_override=definition['name'] if definition else instance['name'],
        object_key_override='media_list',poster_key_override='universe_'+config['media_list']
            if config['media_list'] in UNIVERSES else 'franchises')
