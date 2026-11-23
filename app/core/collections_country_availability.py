"""Regional film catalogues and weekly TV trends via the official TMDb API.

Take ten subscription titles per provider, merge typed TMDb identities, enrich
popularity, then sort the union. Provider count and chart rank never override
TMDb popularity. Only the official TMDb APIs are used.
"""
import math
import re

from core.collections_repository import CollectionRunCancelled
from core.collections_platforms_catalog import PLATFORMS
from core.collections_streaming_source import StreamingSource, COUNTRIES, normalized


def popularity_order(row):
    # Same title tie-break as merge_top_hits_fr.normalize_title.
    return (-row['popularity'],' '.join(row['title'].strip().lower().split()),row['id'])


def local_title_key(value):
    value=re.sub(r'^(the|a|an)\s+','',str(value or '').strip().lower())
    return re.sub(r'[^a-z0-9]+','',value)


class CountryAvailabilitySource(StreamingSource):
    match_local_titles=True
    def provider_catalog(self, country, media_type):
        data=self.cached(['country-availability-providers-v1',country,media_type,self.language],24,
            lambda:self.tmdb('/watch/providers/'+media_type,watch_region=country))
        providers=data.get('results')
        if not isinstance(providers,list) or not providers:
            raise ValueError('collections.streaming_source_invalid')
        unique={}
        for row in providers:
            identifier=row.get('provider_id')
            if type(identifier) is not int or identifier<=0 or not row.get('provider_name'):
                raise ValueError('collections.streaming_source_invalid')
            unique[identifier]={'id':identifier,'name':row['provider_name']}
        providers = []
        for key in ('netflix','prime','apple','disney','max','paramount'):
            spec = PLATFORMS[key]
            aliases = {normalized(name) for name in spec['aliases']}
            ids = sorted(row['id'] for row in unique.values()
                         if row['id'] in spec['ids'] or normalized(row['name']) in aliases)
            if ids:
                providers.append({'id':key,'name':spec['name'],'offer_ids':'|'.join(map(str,ids))})
        return providers

    def provider_titles(self, country, media_type, provider_id):
        def load():
            params={'watch_region':country,'with_watch_providers':provider_id,
                    'with_watch_monetization_types':'flatrate','sort_by':'popularity.desc',
                    'include_adult':'false','page':1}
            if media_type=='movie':params['include_video']='false'
            if getattr(self,'content_language',None):
                params['with_original_language']=self.content_language
            data=self.tmdb('/discover/'+media_type,**params)
            rows=data.get('results')
            if not isinstance(rows,list):raise ValueError('collections.streaming_source_invalid')
            # Empty is normal for rental-only or unavailable regional providers.
            return rows[:10]
        return self.cached(['country-availability-titles-v1',country,media_type,provider_id,self.language,
                            getattr(self,'content_language',None)],6,load)

    def discover(self, country, media_type, platform=None):
        self.partial=False
        self.diagnostics=[]
        if country not in COUNTRIES or media_type not in ('movie','tv'):
            raise ValueError('collections.invalid_country')
        if media_type=='tv':
            return self.tv_trends(country)
        try:
            providers=self.provider_catalog(country,media_type)
        except CollectionRunCancelled:raise
        except Exception as exc:
            self.diagnostics=[{'id':'tmdb_providers','name':'TMDb','state':'error','count':0,
                'source_kind':'country_tmdb_availability',
                'failure':self.failure(exc,'tmdb_providers',country,media_type,'catalog')}]
            raise ValueError('collections.streaming_incomplete') from exc
        if platform is not None:
            providers=[p for p in providers if str(p['id'])==str(platform)]
            if not providers:raise ValueError('collections.streaming_source_invalid')
        merged={}
        failed=False
        for provider in providers:
            self.heartbeat()
            source='tmdb_availability_'+str(provider['id'])+'_'+country.lower()
            diagnostic={'id':source,'name':provider['name'],'country':country,
                        'source_kind':'country_tmdb_availability','state':'error','count':0,
                        'ranking':'tmdb_popularity_desc','failures':[]}
            self.diagnostics.append(diagnostic)
            try:
                titles=self.provider_titles(country,media_type,provider['offer_ids'])
                for rank,title in enumerate(titles,1):
                    identifier=title.get('id')
                    if type(identifier) is not int or identifier<=0:
                        raise ValueError('collections.streaming_source_invalid')
                    row=merged.setdefault(identifier,{'id':identifier,'sources':[],
                        'title':title.get('title') or title.get('name'),
                        'ranks_by_source':{},'source_kinds':{}})
                    if source not in row['sources']:row['sources'].append(source)
                    row['ranks_by_source'][source]=min(rank,row['ranks_by_source'].get(source,rank))
                    row['source_kinds'][source]='country_tmdb_availability'
                diagnostic.update(state='success',count=len(titles))
            except CollectionRunCancelled:raise
            except Exception as exc:
                failed=True
                diagnostic['failure']=self.failure(exc,source,country,media_type,'provider_availability')
        # Match the supplied merger: an incomplete provider collection must not
        # replace a complete existing publication with a different selection.
        if failed:
            self.partial=True
            raise ValueError('collections.streaming_incomplete')
        rows=[]
        for identifier,row in merged.items():
            self.heartbeat()
            try:
                detail=self.cached(['country-availability-detail-v1',media_type,identifier,self.language],6,
                    lambda:self.tmdb('/'+media_type+'/'+str(identifier)))
                title=detail.get('title') if media_type=='movie' else detail.get('name')
                popularity=float(detail.get('popularity') or 0)
                if detail.get('id')!=identifier or not isinstance(title,str) or not title.strip() or not math.isfinite(popularity):
                    raise ValueError('collections.streaming_identity_failed')
                row.update(title=row.get('title') or title,year=str(detail.get('release_date') or detail.get('first_air_date') or '')[:4],
                    popularity=popularity,buzz_score=popularity,imdb_id=detail.get('imdb_id'),
                    original_language=detail.get('original_language'))
                rows.append(row)
            except CollectionRunCancelled:raise
            except Exception as exc:
                self.partial=True
                diagnostic={'id':'tmdb_'+str(identifier),'name':str(identifier),'state':'error','count':0,
                    'source_kind':'country_tmdb_availability',
                    'failure':self.failure(exc,'tmdb_'+str(identifier),country,media_type,'identity')}
                self.diagnostics.append(diagnostic)
                raise ValueError('collections.streaming_incomplete') from exc
        if not rows:raise ValueError('collections.streaming_empty')
        return sorted(rows,key=popularity_order)

    def tv_trends(self, country):
        source = 'tmdb_weekly_tv_'+country.lower()
        kind = 'country_tmdb_trending'
        diagnostic = {'id':source,'name':'TMDb','country':country,'source_kind':kind,
                      'state':'error','count':0}
        self.diagnostics.append(diagnostic)
        ranked = {}
        try:
            for page in range(1,6):
                chart = self.cached(['weekly-tv-trends-v1',self.language,page],6,
                                    lambda:self.tmdb('/trending/tv/week',page=page))
                titles = chart.get('results')
                if not isinstance(titles,list) or (page==1 and not titles):
                    raise ValueError('collections.streaming_source_invalid')
                for offset, title in enumerate(titles,1):
                    self.heartbeat()
                    identifier = title.get('id')
                    if type(identifier) is not int or identifier<=0 or not title.get('name'):
                        raise ValueError('collections.streaming_identity_failed')
                    if identifier in ranked or title.get('adult'):
                        continue
                    if getattr(self,'content_language',None) and title.get('original_language')!=self.content_language:
                        continue
                    offers = self.cached(['weekly-tv-offers-v1',identifier],6,
                                         lambda:self.tmdb(f'/tv/{identifier}/watch/providers'))
                    markets = offers.get('results')
                    if not isinstance(markets,dict):
                        raise ValueError('collections.streaming_source_invalid')
                    regional = markets.get(country,{})
                    if not isinstance(regional,dict):
                        raise ValueError('collections.streaming_source_invalid')
                    if not any(regional.get(mode) for mode in ('flatrate','free','ads')):
                        continue
                    rank = (page-1)*20+offset
                    ranked[identifier] = {'id':identifier,'title':title['name'],
                        'year':str(title.get('first_air_date') or '')[:4],
                        'original_language':title.get('original_language'),
                        'buzz_score':-rank,'sources':[source],
                        'ranks_by_source':{source:rank},'source_kinds':{source:kind}}
                if not titles or page>=chart.get('total_pages',1):
                    break
        except CollectionRunCancelled: raise
        except Exception as exc:
            self.partial = True
            diagnostic['failure'] = self.failure(exc,source,country,'tv','weekly_trends')
            raise ValueError('collections.streaming_incomplete') from exc
        diagnostic.update(state='success',count=len(ranked))
        if not ranked: raise ValueError('collections.streaming_empty')
        return list(ranked.values())

    def original_language(self, media_type, row):
        return row.get('original_language') or super().original_language(media_type,row)
