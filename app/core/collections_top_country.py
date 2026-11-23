"""Ranked TMDb media by origin, independently of streaming market/language."""
import json
from core.collections_media import media_adapter
from core.collections_repository import CollectionRunCancelled, top_country_name, utcnow
from core.collections_streaming import run_streaming_country
from core.collections_streaming_source import StreamingSource, COUNTRIES


class TopCountrySource(StreamingSource):
    country_chart='top'
    minimum_votes=100
    content_language=''
    selection_limit=250

    def original_language(self, media_type, row):
        language=row.get('original_language')
        if not language:raise ValueError('collections.original_language_unknown')
        return language

    def verified_origin(self, media_type, identifier):
        def load():
            data=self.tmdb('/'+media_type+'/'+str(identifier))
            if data.get('id')!=identifier:raise ValueError('collections.streaming_identity_failed')
            if media_type=='movie':
                countries=data.get('production_countries')
                if not isinstance(countries,list):raise ValueError('collections.country_origin_unknown')
                countries=[row.get('iso_3166_1') for row in countries if isinstance(row,dict)]
            else:countries=data.get('origin_country')
            if not isinstance(countries,list) or not countries or any(not isinstance(code,str) or len(code)!=2 or not code.isalpha() or not code.isupper() for code in countries):
                raise ValueError('collections.country_origin_unknown')
            return {'countries':countries,'original_language':data.get('original_language')}
        return self.cached(['country-origin-v1',media_type,identifier],24*30,load)

    def discover(self, country, media_type):
        if country not in COUNTRIES or media_type not in ('movie','tv') or self.country_chart not in ('top','popular'):
            raise ValueError('collections.invalid_configuration')
        today=utcnow().date().isoformat()
        params={'with_origin_country':country,'include_adult':'false',
                'sort_by':'vote_average.desc' if self.country_chart=='top' else 'popularity.desc',
                'vote_count.gte':self.minimum_votes,
                ('primary_release_date.lte' if media_type=='movie' else 'first_air_date.lte'):today}
        if self.content_language:params['with_original_language']=self.content_language
        self.partial=False
        diagnostic={'id':'top_country','name':'TMDb · '+country,'state':'success','count':0,
                    'source_kind':'country_tmdb_chart','country':country,'failures':[],
                    'rejected_origin':0,'minimum_votes':self.minimum_votes}
        self.diagnostics=[diagnostic]
        selected=[];seen=set()
        # Bound discovery to 250 verified titles; overlap between changing
        # popularity pages must never multiply one title's rank or acquisitions.
        for page in range(1,21):
            self.heartbeat()
            try:
                data=self.cached(['top-country-chart-v1',media_type,self.language,params,page],6,
                    lambda:self.tmdb('/discover/'+media_type,page=page,**params))
                if not isinstance(data.get('results'),list) or type(data.get('total_pages')) is not int or data['total_pages']<0:
                    raise ValueError('collections.streaming_source_invalid')
            except CollectionRunCancelled:raise
            except Exception as exc:
                diagnostic.update(state='error',failure=self.failure(exc,'top_country',country,media_type,'chart'))
                raise
            for row in data['results']:
                self.heartbeat()
                identifier=row.get('id') if isinstance(row,dict) else None
                if type(identifier) is not int or identifier<=0:raise ValueError('collections.streaming_source_invalid')
                if identifier in seen:continue
                seen.add(identifier)
                title=row.get('title') or row.get('name')
                released=row.get('release_date') or row.get('first_air_date')
                if row.get('adult') or not isinstance(title,str) or not isinstance(released,str) or len(released)<10 or released[:10]>today:continue
                if type(row.get('vote_count')) is not int or row['vote_count']<self.minimum_votes:continue
                try:origin=self.verified_origin(media_type,identifier)
                except CollectionRunCancelled:raise
                except Exception as exc:
                    self.partial=True
                    diagnostic['identity_skipped']=True
                    diagnostic['failures'].append(self.failure(exc,'top_country',country,media_type,'origin'))
                    continue
                # Independently verify Discover's filter before matching or Arr.
                if country not in origin['countries']:
                    diagnostic['rejected_origin']+=1
                    continue
                if self.content_language and origin['original_language']!=self.content_language:continue
                rank=len(selected)+1
                selected.append({'id':identifier,'title':title,'year':released[:4],
                    'original_language':origin['original_language'],'origin_countries':origin['countries'],
                    'popularity':row.get('popularity',0),'rank':rank,'sources':['top_country'],
                    'ranks_by_source':{'top_country':rank},'source_kinds':{'top_country':'country_tmdb_chart'},'buzz_score':100000-rank})
                if len(selected)>=min(250,self.selection_limit):break
            if len(selected)>=min(250,self.selection_limit) or page>=data['total_pages']:break
        diagnostic.update(count=len(selected),state='warning' if self.partial else 'success')
        if self.partial and not selected:raise ValueError('collections.streaming_incomplete')
        return selected


def run_top_country(db, instance, *, kind='sync', heartbeat=lambda:None,
                    source_factory=TopCountrySource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    def source(key,language):
        result=source_factory(key,language)
        result.country_chart=config.get('country_chart','top')
        result.minimum_votes=config.get('minimum_votes',100)
        result.content_language=config.get('content_language','')
        result.selection_limit=250
        return result
    title=top_country_name(config['country'],config['language'],config.get('country_chart','top'),config.get('content_language',''))
    return run_streaming_country(db,instance,kind=kind,heartbeat=heartbeat,source_factory=source,
        adapter_factory=adapter_factory,title_override=title,object_key_override='top_country')
