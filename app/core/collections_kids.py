"""Popular children's titles available in a selected market, via TMDb Discover."""
import json
from datetime import timedelta

from core.collections_repository import streaming_title, utcnow
from core.collections_streaming import run_streaming_country
from core.collections_streaming_source import StreamingSource, COUNTRIES
from core.collections_media import media_adapter


class KidsSource(StreamingSource):
    content_language = ''
    kids_chart = 'top'

    def original_language(self, media_type, row):
        language=row.get('original_language')
        if not language:
            raise ValueError('collections.original_language_unknown')
        return language

    def discover(self, country, media_type):
        if country not in COUNTRIES or media_type not in ('movie','tv'):
            raise ValueError('collections.invalid_configuration')
        self.partial=False
        diagnostic={'id':'kids','name':'TMDb Kids','state':'success','count':0,
                    'source_kind':'kids_tmdb_popularity','country':country,'failures':[]}
        self.diagnostics=[diagnostic]
        genre=10751 if media_type=='movie' else 10762
        today=utcnow().date().isoformat()
        params={'watch_region':country,'with_watch_monetization_types':'flatrate|free|ads',
                'with_genres':str(genre),'include_adult':'false','sort_by':'popularity.desc',
                ('primary_release_date.lte' if media_type=='movie' else 'first_air_date.lte'):today}
        if self.kids_chart == 'latest':
            params['primary_release_date.gte' if media_type=='movie' else 'first_air_date.gte']=(utcnow().date()-timedelta(days=365)).isoformat()
        if self.content_language:
            params['with_original_language']=self.content_language
        def load():
            rows=[]
            for page in range(1,26):
                data=self.tmdb('/discover/'+media_type,page=page,**params)
                if not isinstance(data.get('results'),list) or type(data.get('total_pages')) is not int:
                    raise ValueError('collections.streaming_source_invalid')
                rows.extend(data['results'])
                if page>=data['total_pages']:
                    break
            return rows
        raw=self.cached(['kids-discover-v2',country,media_type,self.language,params],6,load)
        selected=[]
        seen=set()
        for row in raw:
            self.heartbeat()
            if not isinstance(row,dict) or type(row.get('id')) is not int or row['id']<=0:
                raise ValueError('collections.streaming_source_invalid')
            title=row.get('title') or row.get('name')
            released=row.get('release_date') or row.get('first_air_date')
            if row.get('adult') or genre not in (row.get('genre_ids') or []) or not title or not released or released[:10]>today:
                continue
            if self.kids_chart == 'latest' and released[:10]<(utcnow().date()-timedelta(days=365)).isoformat():
                continue
            if self.content_language and row.get('original_language')!=self.content_language:
                continue
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            rank=len(selected)+1
            selected.append({'id':row['id'],'title':title,'year':released[:4],
                             'original_language':row.get('original_language'),
                             'popularity':row.get('popularity',0),'rank':rank,'sources':['kids'],
                             'ranks_by_source':{'kids':rank},'source_kinds':{'kids':'kids_tmdb_popularity'},
                             'buzz_score':100000-rank})
        diagnostic['count']=len(selected)
        return selected


def run_kids(db, instance, *, kind='sync', heartbeat=lambda:None,
             source_factory=KidsSource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    def source(key, language):
        result=source_factory(key,language)
        result.content_language=config.get('content_language','')
        result.kids_chart=config.get('kids_chart','top')
        return result
    title=streaming_title('kids',config['language'],config['country'],content_language=config.get('content_language',''),kids_chart=config.get('kids_chart','top'))
    return run_streaming_country(db,instance,kind=kind,heartbeat=heartbeat,
                                 source_factory=source,adapter_factory=adapter_factory,
                                 title_override=title,object_key_override='kids',poster_key_override='kids')
