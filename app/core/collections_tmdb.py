"""Read ranked TMDb lists and reuse owned publication and optional Arr."""
import json
from core.collections_tmdb_catalog import CHARTS, tmdb_collection_name
from core.collections_streaming_source import StreamingSource
from core.collections_streaming import run_streaming_country
from core.collections_media import media_adapter


class TMDbChartSource(StreamingSource):
    def discover(self, chart, media_type):
        if chart not in CHARTS or CHARTS[chart][0]!=media_type:
            raise ValueError('collections.streaming_source_invalid')
        self.partial=False
        diagnostic={'id':'tmdb','name':tmdb_collection_name(chart,self.language),
                    'state':'success','count':0,'source_kind':'tmdb_chart','failures':[]}
        self.diagnostics=[diagnostic]
        operation=CHARTS[chart][1]
        endpoint=('/trending/'+media_type+'/'+operation.split('/')[1]
                  if operation.startswith('trending/') else '/'+media_type+'/'+operation)
        def load():
            rows=[]
            expected=None
            seen_pages=set()
            for page in range(1,21):
                data=self.tmdb(endpoint,page=page)
                if not isinstance(data.get('results'),list) or type(data.get('total_results')) is not int or data['total_results']<0:
                    raise ValueError('collections.streaming_source_invalid')
                if expected is None:expected=min(250,data['total_results'])
                page_ids=[row.get('id') for row in data['results'] if isinstance(row,dict)]
                if len(page_ids)!=len(data['results']) or any(type(i) is not int or i<=0 for i in page_ids) or len(set(page_ids))!=len(page_ids):
                    raise ValueError('collections.streaming_source_invalid')
                # Popularity changes while pages are fetched. Keep the first
                # rank of overlapping titles and fetch the next page to fill.
                rows.extend(row for row in data['results'] if row['id'] not in seen_pages)
                seen_pages.update(page_ids)
                if len(rows)>=expected:break
                if not data['results']:raise ValueError('collections.streaming_source_invalid')
            if len(rows)<expected:raise ValueError('collections.streaming_source_invalid')
            rows=rows[:expected]
            seen=set()
            result=[]
            for rank,row in enumerate(rows,1):
                self.heartbeat()
                if not isinstance(row,dict) or type(row.get('id')) is not int or row['id']<=0 or row['id'] in seen:
                    raise ValueError('collections.streaming_source_invalid')
                title=row.get('title') or row.get('name')
                if not isinstance(title,str) or not title.strip():raise ValueError('collections.streaming_source_invalid')
                if row.get('media_type',media_type)!=media_type:raise ValueError('collections.streaming_source_invalid')
                seen.add(row['id'])
                result.append({'id':row['id'],'title':title,'year':str(row.get('release_date') or row.get('first_air_date') or '')[:4],
                               'popularity':row.get('popularity',0),'rank':rank,'sources':['tmdb'],
                               'ranks_by_source':{'tmdb':rank},'source_kinds':{'tmdb':'tmdb_chart'},'buzz_score':100000-rank})
            return result
        try:result=self.cached(['tmdb-chart-v2',chart,self.language],1 if operation=='trending/day' else 6,load)
        except Exception:
            diagnostic['state']='error'
            raise
        diagnostic['count']=len(result)
        return result


def run_tmdb(db, instance, *, kind='sync', heartbeat=lambda:None,
             source_factory=TMDbChartSource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    chart=config.get('tmdb_chart','top_movies')
    scoped={**config,'country':chart}
    return run_streaming_country(db,{**instance,'config_json':json.dumps(scoped)},kind=kind,
        heartbeat=heartbeat,source_factory=source_factory,adapter_factory=adapter_factory,
        title_override=tmdb_collection_name(chart,config['language']),object_key_override='tmdb',
        poster_key_override='tmdb_'+chart)
