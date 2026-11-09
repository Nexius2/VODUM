"""IMDb award winner data, typed TMDb identities and shared Arr publication."""
import json
import re
import yaml
from core.collections_awards_catalog import AWARDS, CATALOG, award_period, awards_collection_name
from core.collections_repository import CollectionRunCancelled
from core.collections_streaming_source import StreamingSource, PUBLIC_HEADERS
from core.collections_streaming import run_streaming_country
from core.collections_media import media_adapter


def winner_ids(data, spec, period, media_type):
    if not isinstance(data,dict) or not data:raise ValueError('collections.awards_source_invalid')
    def normalized(value):
        return [str(x).casefold() for x in (value if isinstance(value,list) else [value]) if x]
    allowed_awards=normalized(spec.get('award_filter',[]))
    allowed_categories=normalized(spec.get('category_filter_tv' if media_type=='tv' and spec.get('category_filter_tv') else 'category_filter',[]))
    by_year={}
    for year,awards in data.items():
        year=str(year)
        if not re.fullmatch(r'[0-9]{4}(?:-[0-9]+)?',year) or not isinstance(awards,dict):
            raise ValueError('collections.awards_source_invalid')
        ids=[]
        for award,categories in awards.items():
            if not isinstance(categories,dict):raise ValueError('collections.awards_source_invalid')
            if allowed_awards and str(award).casefold() not in allowed_awards:continue
            for category,entries in categories.items():
                if allowed_categories and str(category).casefold() not in allowed_categories:continue
                if not isinstance(entries,dict) or not isinstance(entries.get('winner'),list):
                    raise ValueError('collections.awards_source_invalid')
                for identifier in entries['winner']:
                    if not isinstance(identifier,str) or not re.fullmatch(r'tt[0-9]+',identifier):
                        raise ValueError('collections.awards_source_invalid')
                    if identifier not in ids:ids.append(identifier)
        if ids:by_year[year]=ids
    years=sorted(by_year,reverse=True)
    if period=='latest':years=years[:1]
    elif period!='all':years=[year for year in years if year.split('-')[0]==period]
    if not years:raise ValueError('collections.awards_source_unavailable')
    result=[];seen=set()
    for year in years:
        for identifier in by_year[year]:
            if identifier not in seen:result.append((identifier,year));seen.add(identifier)
    return result


class AwardsSource(StreamingSource):
    period='latest'
    sort='rank'

    def dataset(self, award):
        url=CATALOG['dataset_url_template'].format(event_id=AWARDS[award]['event_id'])
        def load():
            self.heartbeat()
            response=self.http.get(url,headers=PUBLIC_HEADERS,timeout=(10,30),stream=True)
            try:
                response.raise_for_status()
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    self.heartbeat();size+=len(chunk)
                    if size>8_000_000:raise ValueError('collections.awards_source_invalid')
                    chunks.append(chunk)
                try:data=yaml.safe_load(b''.join(chunks))
                except yaml.YAMLError as exc:raise ValueError('collections.awards_source_invalid') from exc
                if not isinstance(data,dict):raise ValueError('collections.awards_source_invalid')
                # Normalize YAML scalar keys before storing JSON for repeatable cache reads.
                return json.loads(json.dumps(data))
            finally:response.close()
        return self.cached(['awards-dataset-v1',award],24,load)

    def discover(self, award, media_type):
        if award not in AWARDS or ('movie' if media_type=='movie' else 'shows') not in AWARDS[award]['media_types']:
            raise ValueError('collections.awards_invalid_award')
        self.partial=False
        diagnostic={'id':'awards','name':AWARDS[award]['name'],'source_kind':'awards_winners','state':'success','count':0,'failures':[]}
        self.diagnostics=[diagnostic]
        try:
            ids=winner_ids(self.dataset(award),AWARDS[award],award_period(self.period),media_type)
        except CollectionRunCancelled:raise
        except Exception as exc:
            diagnostic.update(state='error',failure=self.failure(exc,'awards',award,media_type,'dataset'))
            raise
        rows=[]
        for identifier,year in ids:
            self.heartbeat()
            try:
                data=self.cached(['awards-identity-v1',identifier,self.language],24*30,
                                 lambda i=identifier:self.tmdb('/find/'+i,external_source='imdb_id'))
                matches=data.get('movie_results' if media_type=='movie' else 'tv_results')
                if not isinstance(matches,list):raise ValueError('collections.streaming_identity_failed')
                if not matches and any(data.get(key) for key in ('movie_results','tv_results','tv_episode_results')):continue
                if len(matches)!=1 or type(matches[0].get('id')) is not int or matches[0]['id']<=0:
                    raise ValueError('collections.streaming_identity_failed')
                media=matches[0];title=media.get('title') or media.get('name')
                if not title:raise ValueError('collections.streaming_identity_failed')
                rank=len(rows)+1
                rows.append({**media,'title':title,'year':str(media.get('release_date') or media.get('first_air_date') or '')[:4],
                             'imdb_id':identifier,'award_year':year,'rank':rank,'sources':['awards'],
                             'ranks_by_source':{'awards':rank},'source_kinds':{'awards':'awards_winners'},'buzz_score':100000-rank})
            except CollectionRunCancelled:raise
            except Exception as exc:
                self.partial=True
                diagnostic['failures'].append(self.failure(exc,'awards',award,media_type,'identity'))
        if not rows:
            diagnostic['state']='error' if self.partial else 'success'
            # The winners dataset was read successfully. Failed identities or
            # winners belonging to another media type are not source outages.
            raise ValueError('collections.streaming_incomplete' if self.partial else 'collections.streaming_empty')
        if self.sort=='release':rows.sort(key=lambda row:str(row.get('release_date') or row.get('first_air_date') or ''),reverse=True)
        elif self.sort=='popularity':rows.sort(key=lambda row:float(row.get('popularity') or 0),reverse=True)
        diagnostic.update(state='warning' if self.partial else 'success',count=len(rows),years=sorted({row['award_year'] for row in rows},reverse=True))
        return rows


def run_awards(db, instance, *, kind='sync', heartbeat=lambda:None, source_factory=AwardsSource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    award=config.get('award','oscars');period=config.get('award_period','latest')
    def source(key,language):
        result=source_factory(key,language);result.period=period;result.sort=config['sort'];return result
    scoped={**config,'country':award}
    return run_streaming_country(db,{**instance,'config_json':json.dumps(scoped)},kind=kind,heartbeat=heartbeat,
        source_factory=source,adapter_factory=adapter_factory,object_key_override='awards',
        title_override=awards_collection_name(award,period,config['language']),poster_key_override='awards_'+award)
