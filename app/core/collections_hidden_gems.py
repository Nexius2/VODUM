"""Highly rated, less popular TMDb titles, using shared Plex/Jellyfin and Arr flows."""
import json
import math
from datetime import date

from core.collections_media import media_adapter
from core.collections_repository import utcnow, hidden_gems_name
from core.collections_streaming import run_streaming_country
from core.collections_streaming_source import StreamingSource



def eligible(row, minimum_rating, minimum_votes, maximum_popularity, today):
    if row.get('adult') or row.get('media_type') not in (None, 'movie', 'tv'):
        return False
    metrics = [row.get(key) for key in ('vote_average','vote_count','popularity')]
    if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in metrics):
        return False
    rating, votes, popularity = metrics
    released = row.get('release_date') or row.get('first_air_date')
    try:
        released = date.fromisoformat(released)
    except (ValueError, TypeError):
        return False
    return (released <= today and minimum_rating <= rating <= 10
            and votes >= minimum_votes and 0 <= popularity <= maximum_popularity)


class HiddenGemsSource(StreamingSource):
    minimum_rating = 7.5
    minimum_votes = 200
    maximum_popularity = 10
    selection_limit = 250

    def discover(self, unused, media_type):
        if media_type not in ('movie','tv'):
            raise ValueError('collections.streaming_source_invalid')
        today = utcnow().date()
        params = {'include_adult':'false', 'sort_by':'vote_average.desc',
                  'vote_average.gte':self.minimum_rating, 'vote_count.gte':self.minimum_votes,
                  ('primary_release_date.lte' if media_type=='movie' else 'first_air_date.lte'):today.isoformat()}
        self.partial = False
        diagnostic = {'id':'hidden_gems','name':'TMDb','state':'success','count':0,
                      'source_kind':'hidden_gems_tmdb','failures':[],
                      'minimum_rating':self.minimum_rating,'minimum_votes':self.minimum_votes,
                      'maximum_popularity':self.maximum_popularity}
        self.diagnostics = [diagnostic]
        selected, seen = [], set()
        # Discover has no documented popularity ceiling: apply it locally on
        # every candidate before publication or acquisition, with a bounded scan.
        for page in range(1,51):
            self.heartbeat()
            try:
                data = self.cached(['hidden-gems-v1',media_type,self.language,params,page],6,
                    lambda:self.tmdb('/discover/'+media_type,page=page,**params))
                if (not isinstance(data,dict) or not isinstance(data.get('results'),list)
                    or type(data.get('total_pages')) is not int or data['total_pages']<0
                    or (not data['results'] and page < data['total_pages'])):
                    raise ValueError('collections.streaming_source_invalid')
                for row in data['results']:
                    self.heartbeat()
                    if (not isinstance(row,dict) or type(row.get('id')) is not int or row['id']<=0
                        or row.get('media_type',media_type)!=media_type):
                        raise ValueError('collections.streaming_source_invalid')
                    if row['id'] in seen:continue
                    seen.add(row['id'])
                    if not eligible(row,self.minimum_rating,self.minimum_votes,self.maximum_popularity,today):continue
                    title = row.get('title') or row.get('name')
                    if not isinstance(title,str) or not title.strip():
                        raise ValueError('collections.streaming_source_invalid')
                    rank = len(selected)+1
                    selected.append({'id':row['id'],'title':title,
                        'year':(row.get('release_date') or row.get('first_air_date'))[:4],
                        'vote_average':row['vote_average'],'vote_count':row['vote_count'],
                        'popularity':row['popularity'],'rank':rank,'sources':['hidden_gems'],
                        'ranks_by_source':{'hidden_gems':rank},
                        'source_kinds':{'hidden_gems':'hidden_gems_tmdb'},'buzz_score':100000-rank})
                    if len(selected)>=self.selection_limit:break
            except Exception:
                diagnostic['state']='error'
                raise
            if len(selected)>=self.selection_limit or page>=data['total_pages']:break
        diagnostic.update(count=len(selected),pages=page)
        return selected


def run_hidden_gems(db, instance, *, kind='sync', heartbeat=lambda:None,
                    source_factory=HiddenGemsSource, adapter_factory=media_adapter):
    config = json.loads(instance['config_json'])
    def source(key, language):
        result = source_factory(key,language)
        result.minimum_rating = config.get('minimum_rating',7.5)
        result.minimum_votes = config.get('minimum_votes',200)
        result.maximum_popularity = config.get('maximum_popularity',10)
        # Match a wider pool to fill the local limit; Arr still receives only
        # the highest ranked configured number through the shared engine.
        result.selection_limit = 250
        return result
    scoped = {**config,'country':'hidden_gems'}
    return run_streaming_country(db,{**instance,'config_json':json.dumps(scoped)},kind=kind,
        heartbeat=heartbeat,source_factory=source,adapter_factory=adapter_factory,
        title_override=hidden_gems_name(config['language']),object_key_override='hidden_gems')
