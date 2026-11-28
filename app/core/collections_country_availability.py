"""Top streaming by country: the top of each major subscription platform.

Films and series use the same method. The platforms are the subscription
services TMDb lists for the country, in TMDb's display order for that country.
Each platform contributes its own ranking: Netflix's official weekly Top 10
for the country first, then JustWatch's popularity ranking in that country.
When JustWatch cannot rank a platform (unavailable, changed, nothing listed),
TMDb popularity among the titles TMDb lists on that platform is used instead.
Rankings are cumulated rank by rank (every platform's number 1, then every
number 2...), duplicates are merged, and the depth per platform grows until
the requested number of titles is reached. Only free sources without account
or paid key are used (TMDb API, Netflix Top 10 pages, JustWatch public GraphQL).
"""
import math
import re

from core.collections_repository import CollectionRunCancelled
from core.collections_platforms_catalog import PLATFORMS
from core.collections_streaming_source import (StreamingSource, COUNTRIES, PUBLIC_HEADERS,
                                               netflix_chart, normalized)
from logging_utils import get_logger

MAX_PLATFORMS = 10       # major platforms kept per country
MAX_PROVIDER_PROBES = 30 # providers checked to find them (rental stores are empty)
MAX_PAGES = 5            # TMDb pages per platform (20 titles each)
DEFAULT_TARGET = 20      # titles per platform when the collection has no limit
JUSTWATCH_URL = 'https://apis.justwatch.com/graphql'
JUSTWATCH_KIND = 'country_justwatch_popularity'
JUSTWATCH_PAGE = 50      # titles per JustWatch request
JUSTWATCH_MAX_PAGES = 2  # 100 titles per platform at most
# Reseller channels repeat a service already counted under its own name.
RESELLER = re.compile(r'\b(amazon|apple tv|roku premium|molotov|free|orange|sfr|bouygues|canal\+?)\s+channels?\b', re.I)


def local_title_key(value):
    value=re.sub(r'^(the|a|an)\s+','',str(value or '').strip().lower())
    return re.sub(r'[^a-z0-9]+','',value)


def platform_family(provider):
    aliases={normalized(name) for name in [provider['name']]}
    for key,spec in PLATFORMS.items():
        if provider['id'] in spec['ids'] or aliases & {normalized(name) for name in spec['aliases']}:
            return key
    return normalized(re.sub(r'\s+(standard\s+)?with\s+ads$','',provider['name'],flags=re.I)) or str(provider['id'])


class CountryAvailabilitySource(StreamingSource):
    match_local_titles=True
    target_count=0

    # ---- platforms -----------------------------------------------------
    def provider_catalog(self, country, media_type):
        """Subscription-capable services of the country, in TMDb display order,
        grouped by family (Netflix and Netflix with ads are one platform)."""
        data=self.cached(['country-availability-providers-v2',country,media_type,self.language],24,
            lambda:self.tmdb('/watch/providers/'+media_type,watch_region=country))
        providers=data.get('results')
        if not isinstance(providers,list) or not providers:
            raise ValueError('collections.streaming_source_invalid')
        rows=[]
        for position,row in enumerate(providers):
            identifier=row.get('provider_id') if isinstance(row,dict) else None
            name=row.get('provider_name') if isinstance(row,dict) else None
            if type(identifier) is not int or identifier<=0 or not isinstance(name,str) or not name.strip():
                raise ValueError('collections.streaming_source_invalid')
            if RESELLER.search(name):continue
            priorities=row.get('display_priorities') if isinstance(row.get('display_priorities'),dict) else {}
            priority=priorities.get(country,row.get('display_priority'))
            priority=priority if type(priority) is int else 10**6
            rows.append({'id':identifier,'name':name.strip(),'priority':priority,'position':position})
        rows.sort(key=lambda row:(row['priority'],row['position'],row['id']))
        families={}
        for row in rows:
            key=platform_family(row)
            family=families.setdefault(key,{'id':key,'name':PLATFORMS[key]['name'] if key in PLATFORMS else row['name'],
                                            'provider_ids':[],'priority':row['priority']})
            family['provider_ids'].append(row['id'])
        return [{**family,'offer_ids':'|'.join(map(str,sorted(family['provider_ids'])))} for family in families.values()]

    def provider_page(self, country, media_type, offer_ids, page):
        def load():
            params={'watch_region':country,'with_watch_providers':offer_ids,
                    'with_watch_monetization_types':'flatrate','sort_by':'popularity.desc',
                    'include_adult':'false','page':page}
            if media_type=='movie':params['include_video']='false'
            if getattr(self,'content_language',None):
                params['with_original_language']=self.content_language
            data=self.tmdb('/discover/'+media_type,**params)
            rows=data.get('results')
            pages=data.get('total_pages',1)
            if not isinstance(rows,list) or type(pages) is not int or pages<0:
                raise ValueError('collections.streaming_source_invalid')
            return {'results':rows,'total_pages':pages}
        return self.cached(['country-availability-page-v2',country,media_type,offer_ids,page,self.language,
                            getattr(self,'content_language',None)],6,load)

    # ---- Netflix official Top 10 ----------------------------------------
    def netflix_official(self, country, media_type, platform):
        """Official weekly Top 10 of the country, mapped to TMDb titles that
        TMDb lists on Netflix in that country. Never fatal: the TMDb ranking
        of the platform is used alone when the page cannot be read."""
        slug=COUNTRIES[country][0]
        url='https://www.netflix.com/tudum/top10/'+slug+('/tv' if media_type=='tv' else '')
        diagnostic={'id':'nfx_official_'+country.lower(),'name':'Netflix Top 10','country':country,
                    'source_kind':'platform_chart','url':url,'state':'error','count':0,'failures':[]}
        self.diagnostics.append(diagnostic)
        def load():
            response=self.http.get(url,headers=PUBLIC_HEADERS,timeout=(10,25))
            response.raise_for_status()
            return netflix_chart(response.text,country,media_type)
        try:
            chart=self.cached(['netflix-official-chart-v1',country,media_type],6,load)
        except CollectionRunCancelled:raise
        except Exception as exc:
            diagnostic['failures'].append(self.fallback_failure(exc,diagnostic['id'],country,media_type,'platform_chart'))
            diagnostic['state']='warning'
            return []
        rows=[]
        unresolved=0
        for row in chart:
            self.heartbeat()
            try:
                media=self.netflix_identity(row['title'],country,media_type,platform)
            except CollectionRunCancelled:raise
            except Exception as exc:
                diagnostic['identity_skipped']=True
                diagnostic['failures'].append(self.fallback_failure(exc,diagnostic['id'],country,media_type,'identity'))
                continue
            if media.get('unresolved'):
                # A title TMDb cannot tie to one Netflix title of this country is
                # left out: the TMDb ranking of Netflix still fills the platform.
                unresolved+=1
                continue
            if any(existing['id']==media['id'] for existing in rows):continue
            rows.append(media)
        diagnostic.update(count=len(rows),unresolved=unresolved,
                          state='warning' if diagnostic['failures'] else 'success')
        return rows

    def netflix_identity(self, title, country, media_type, platform):
        """Map one Netflix Top 10 title to TMDb. Returns {'unresolved': True}
        (cached like a match, so it is not searched again at every run) when no
        single title on Netflix in this country fits."""
        def load():
            # Netflix publishes English titles whatever the country: search and
            # compare them in English, then show the presentation-language title.
            results=self.tmdb('/search/'+media_type,query=title,include_adult='false',language='en-US').get('results')
            if not isinstance(results,list):raise ValueError('collections.streaming_source_invalid')
            results=[row for row in results[:10] if isinstance(row,dict) and type(row.get('id')) is int and row['id']>0]
            wanted=normalized(title)
            named=[row for row in results if wanted in {normalized(row.get(key)) for key in ('title','name','original_title','original_name')}]
            pool=named or results[:5]
            on_netflix=[row for row in pool if self.on_platform(row['id'],country,media_type,platform)]
            if len(on_netflix)>1 and named:
                exact=[row for row in on_netflix if row in named]
                on_netflix=exact if exact else on_netflix
            if len(on_netflix)!=1:
                get_logger('collections.streaming').info(
                    'Netflix Top 10 title not matched | country=%s | media_type=%s | candidates=%s',
                    country,media_type,len(on_netflix))
                return {'unresolved':True}
            match=on_netflix[0]
            if not str(self.language).lower().startswith('en'):
                try:
                    detail=self.cached(['country-availability-detail-v1',media_type,match['id'],self.language],6,
                        lambda:self.tmdb('/'+media_type+'/'+str(match['id'])))
                    localized=detail.get('title') if media_type=='movie' else detail.get('name')
                    if detail.get('id')==match['id'] and isinstance(localized,str) and localized.strip():
                        match={**match,('title' if media_type=='movie' else 'name'):localized}
                except CollectionRunCancelled:raise
                except Exception:
                    pass  # the English title still identifies the media
            return self.tmdb_row(match,media_type)
        return self.cached(['netflix-official-identity-v2',country,media_type,self.language,title],24,load)

    def on_platform(self, identifier, country, media_type, platform):
        offers=self.cached(['country-availability-offers-v1',media_type,identifier],24,
                           lambda:self.tmdb('/'+media_type+'/'+str(identifier)+'/watch/providers'))
        regional=(offers.get('results') or {}).get(country) if isinstance(offers.get('results'),dict) else None
        if not isinstance(regional,dict):return False
        ids=set(platform['provider_ids'])
        return any(isinstance(row,dict) and row.get('provider_id') in ids for row in regional.get('flatrate') or [])

    @staticmethod
    def tmdb_row(row, media_type):
        title=row.get('title') if media_type=='movie' else row.get('name')
        popularity=float(row.get('popularity') or 0)
        if not isinstance(title,str) or not title.strip() or not math.isfinite(popularity):
            raise ValueError('collections.streaming_identity_failed')
        return {'id':row['id'],'title':title,'year':str(row.get('release_date') or row.get('first_air_date') or '')[:4],
                'popularity':popularity,'original_language':row.get('original_language')}

    # ---- JustWatch country popularity -------------------------------------
    # Public GraphQL endpoint used by the JustWatch website: free, no account or
    # key. Unofficial, so every failure falls back to TMDb for that platform.
    JUSTWATCH_PACKAGES_QUERY = """query GetProviders($country: Country!) {
  packages(country: $country, platform: WEB, includeAddons: true) {
    packageId shortName clearName monetizationTypes
  }
}"""
    JUSTWATCH_POPULAR_QUERY = """query GetPopularTitles($country: Country!, $language: Language!, $first: Int!, $offset: Int, $filter: TitleFilter) {
  popularTitles(country: $country, filter: $filter, first: $first, offset: $offset, sortBy: POPULAR, sortRandomSeed: 0) {
    edges { node { objectType content(country: $country, language: $language) {
      title originalReleaseYear externalIds { imdbId tmdbId }
    } } }
  }
}"""

    def justwatch(self, operation, query, variables):
        self.heartbeat()
        response=self.http.post(JUSTWATCH_URL,json={'operationName':operation,'query':query,'variables':variables},
                                headers=PUBLIC_HEADERS,timeout=(10,25))
        response.raise_for_status()
        data=response.json()
        if not isinstance(data,dict) or data.get('errors') or not isinstance(data.get('data'),dict):
            raise ValueError('collections.streaming_source_invalid')
        return data['data']

    def justwatch_packages(self, country):
        """{TMDb provider id: JustWatch short name} for subscription packages.
        JustWatch package ids are the provider ids TMDb publishes."""
        def load():
            rows=self.justwatch('GetProviders',self.JUSTWATCH_PACKAGES_QUERY,{'country':country}).get('packages')
            if not isinstance(rows,list) or not rows:raise ValueError('collections.streaming_source_invalid')
            result={}
            for row in rows:
                if not isinstance(row,dict):continue
                identifier,short=row.get('packageId'),row.get('shortName')
                types=row.get('monetizationTypes') or []
                if type(identifier) is int and isinstance(short,str) and short and \
                        any(str(kind).upper()=='FLATRATE' for kind in types):
                    result[str(identifier)]=short
            if not result:raise ValueError('collections.streaming_source_invalid')
            return result
        return {int(key):value for key,value in self.cached(['justwatch-packages-v1',country],24,load).items()}

    def justwatch_page(self, country, media_type, packages, page):
        """One page of JustWatch's popularity ranking for these packages in the
        country, as TMDb-typed rows. Titles without a TMDb id are skipped."""
        def load():
            data=self.justwatch('GetPopularTitles',self.JUSTWATCH_POPULAR_QUERY,{
                'country':country,'language':str(self.language or 'en').split('-')[0].lower(),
                'first':JUSTWATCH_PAGE,'offset':page*JUSTWATCH_PAGE or None,
                'filter':{'packages':list(packages),'objectTypes':['MOVIE' if media_type=='movie' else 'SHOW']}})
            edges=(data.get('popularTitles') or {}).get('edges')
            if not isinstance(edges,list):raise ValueError('collections.streaming_source_invalid')
            rows=[]
            for edge in edges:
                node=edge.get('node') if isinstance(edge,dict) else None
                content=node.get('content') if isinstance(node,dict) else None
                if not isinstance(content,dict):continue
                ids=content.get('externalIds') or {}
                try:identifier=int(str(ids.get('tmdbId') or '').strip())
                except ValueError:continue
                title=content.get('title')
                if identifier<=0 or not isinstance(title,str) or not title.strip():continue
                year=content.get('originalReleaseYear')
                rows.append({'id':identifier,'title':title.strip(),'year':str(year) if type(year) is int else '',
                             'popularity':0.0,'original_language':None,'imdb_id':ids.get('imdbId') or None})
            return rows
        return self.cached(['justwatch-popular-v1',country,media_type,list(packages),page,self.language],6,load)

    def fallback_failure(self, exc, provider, country, media_type, stage):
        """A source replaced by a fallback: logged as a warning, never an error."""
        response=getattr(exc,'response',None)
        status=getattr(response,'status_code',None)
        status=status if isinstance(status,int) else None
        get_logger('collections.streaming').warning(
            'Streaming source replaced by TMDb | provider=%s | country=%s | media_type=%s | stage=%s | http_status=%s | error_type=%s',
            provider,country,media_type,stage,status,type(exc).__name__)
        return {'provider':provider,'country':country,'media_type':media_type,'stage':stage,
                'http_status':status,'error_type':type(exc).__name__}

    # ---- cumulation --------------------------------------------------------
    def discover(self, country, media_type, platform=None):
        self.partial=False
        self.diagnostics=[]
        if country not in COUNTRIES or media_type not in ('movie','tv'):
            raise ValueError('collections.invalid_country')
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
        target=self.target_count if type(self.target_count) is int and self.target_count>0 else 0
        language=getattr(self,'content_language',None)
        platforms=[]
        # Keep the first platforms of the country that actually offer titles in
        # subscription; rental stores and empty services are skipped.
        for provider in providers[:MAX_PROVIDER_PROBES]:
            if len(platforms)>=MAX_PLATFORMS:break
            self.heartbeat()
            source='tmdb_availability_'+str(provider['id'])+'_'+country.lower()
            try:
                page=self.provider_page(country,media_type,provider['offer_ids'],1)
            except CollectionRunCancelled:raise
            except Exception as exc:
                self.diagnostics.append({'id':source,'name':provider['name'],'country':country,
                    'source_kind':'country_tmdb_availability','state':'error','count':0,
                    'failure':self.failure(exc,source,country,media_type,'provider_availability')})
                # An incomplete platform set must not replace the existing collection.
                self.partial=True
                raise ValueError('collections.streaming_incomplete') from exc
            if not page['results']:continue
            platforms.append({**provider,'source':source,'pages':[page['results']],'total_pages':page['total_pages'],
                              'ranking':[]})
        if not platforms:raise ValueError('collections.streaming_empty')
        # Country popularity per platform from JustWatch; TMDb (already read
        # above) stays the fallback for any platform JustWatch cannot rank.
        packages={}
        try:
            packages=self.justwatch_packages(country)
        except CollectionRunCancelled:raise
        except Exception as exc:
            self.diagnostics.append({'id':'justwatch_'+country.lower(),'name':'JustWatch','country':country,
                'source_kind':JUSTWATCH_KIND,'state':'warning','count':0,
                'failures':[self.fallback_failure(exc,'justwatch_'+country.lower(),country,media_type,'catalog')]})
        for item in platforms:
            if item['id']=='netflix':
                item['official']=self.netflix_official(country,media_type,item)
                if language:
                    item['official']=[row for row in item['official'] if row.get('original_language')==language]
            diagnostic={'id':item['source'],'name':item['name'],'country':country,
                'source_kind':'country_tmdb_availability','state':'success','count':0,
                'ranking':'tmdb_popularity_desc','failures':[]}
            self.diagnostics.append(diagnostic)
            item['diagnostic']=diagnostic
            shorts=sorted({packages[i] for i in item['provider_ids'] if i in packages})
            if not shorts:continue
            try:
                first=self.justwatch_page(country,media_type,shorts,0)
            except CollectionRunCancelled:raise
            except Exception as exc:
                diagnostic['failures'].append(self.fallback_failure(exc,item['source'],country,media_type,'justwatch'))
                continue
            if not first:continue  # nothing ranked by JustWatch: keep TMDb
            item.update(mode='justwatch',packages=shorts,pages=[first],
                        total_pages=2 if len(first)>=JUSTWATCH_PAGE else 1)
            diagnostic.update(source_kind=JUSTWATCH_KIND,ranking='justwatch_popularity_country')

        def rankings():
            for item in platforms:
                ranked,seen=[],set()
                for row in item.get('official',[]):
                    ranked.append({**row,'kind':'platform_chart'});seen.add(row['id'])
                justwatch=item.get('mode')=='justwatch'
                for page in item['pages']:
                    for row in page:
                        identifier=row.get('id') if isinstance(row,dict) else None
                        if type(identifier) is not int or identifier<=0 or identifier in seen or row.get('adult'):continue
                        if justwatch:
                            media=dict(row)
                            if language:
                                try:
                                    media['original_language']=self.original_language(media_type,media)
                                except CollectionRunCancelled:raise
                                except Exception:continue
                                if media['original_language']!=language:continue
                        else:
                            try:media=self.tmdb_row(row,media_type)
                            except ValueError:continue  # one malformed title never blocks the chart
                        seen.add(identifier)
                        ranked.append({**media,'kind':JUSTWATCH_KIND if justwatch else 'country_tmdb_availability'})
                item['ranking']=ranked

        def merged(depth):
            rows={}
            for order,item in enumerate(platforms):
                for rank,media in enumerate(item['ranking'][:depth],1):
                    row=rows.setdefault(media['id'],{**{k:media.get(k) for k in ('id','title','year','popularity','original_language')},
                        'sources':[],'ranks_by_source':{},'source_kinds':{},'_best':(rank,order)})
                    if media.get('imdb_id') and not row.get('imdb_id'):row['imdb_id']=media['imdb_id']
                    row['sources'].append(item['source'])
                    row['ranks_by_source'][item['source']]=rank
                    row['source_kinds'][item['source']]=media['kind']
                    row['_best']=min(row['_best'],(rank,order))
            # Rank by rank across platforms (every number 1, then every number 2...),
            # a title on several platforms first, then the country's platform order.
            return sorted(rows.values(),key=lambda row:(row['_best'][0],-len(row['sources']),row['_best'][1],row['id']))

        def unfinished():
            return [item for item in platforms if len(item['pages'])<min(
                JUSTWATCH_MAX_PAGES if item.get('mode')=='justwatch' else MAX_PAGES,item['total_pages'])]

        def next_page(item):
            if item.get('mode')=='justwatch':
                try:
                    page=self.justwatch_page(country,media_type,item['packages'],len(item['pages']))
                except CollectionRunCancelled:raise
                except Exception as exc:
                    # Keep the JustWatch titles already read; stop going deeper.
                    item['diagnostic']['failures'].append(self.fallback_failure(exc,item['source'],country,media_type,'justwatch'))
                    item['total_pages']=len(item['pages'])
                    return
                item['pages'].append(page)
                item['total_pages']=len(item['pages'])+1 if len(page)>=JUSTWATCH_PAGE else len(item['pages'])
                return
            try:
                page=self.provider_page(country,media_type,item['offer_ids'],len(item['pages'])+1)
            except CollectionRunCancelled:raise
            except Exception as exc:
                item['diagnostic'].update(state='error',failure=self.failure(exc,item['source'],country,media_type,'provider_availability'))
                self.partial=True
                raise ValueError('collections.streaming_incomplete') from exc
            item['pages'].append(page['results'])
            if not page['results']:item['total_pages']=len(item['pages'])

        rankings()
        while target:
            pending=unfinished()
            # Rankings are complete up to the shortest platform still paginating.
            depth=min(len(item['ranking']) for item in pending) if pending else max(len(item['ranking']) for item in platforms)
            if len(merged(depth))>=target or not pending:break
            for item in pending:
                self.heartbeat()
                next_page(item)
            rankings()
        rows=merged(depth)[:target] if target else merged(DEFAULT_TARGET)
        counts={}
        for position,row in enumerate(rows,1):
            row.pop('_best',None)
            # Higher is better; the engine keeps this order.
            row['buzz_score']=len(rows)-position+1
            for source in row['sources']:counts[source]=counts.get(source,0)+1
        for item in platforms:
            item['diagnostic']['count']=counts.get(item['source'],0)
            if item['diagnostic']['failures'] and item['diagnostic']['state']=='success':
                item['diagnostic']['state']='warning'
        if media_type=='movie':
            for row in rows:
                # IMDb ids let the engine match local films without a TMDb id.
                self.heartbeat()
                try:
                    detail=self.cached(['country-availability-detail-v1',media_type,row['id'],self.language],6,
                        lambda:self.tmdb('/'+media_type+'/'+str(row['id'])))
                    if detail.get('id')==row['id']:row['imdb_id']=detail.get('imdb_id')
                except CollectionRunCancelled:raise
                except Exception:
                    pass  # The engine resolves external ids itself when needed.
        if not rows:raise ValueError('collections.streaming_empty')
        return rows

    def original_language(self, media_type, row):
        return row.get('original_language') or super().original_language(media_type,row)
