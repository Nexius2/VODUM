"""Shared country/provider charts, adapted from top_hit_Movies/top_hit_series.

Keep provider identity and ranks so platform collections can reuse discovery.
Country-wide popularity is never substituted for a provider's chart.
"""
import json
import re
import unicodedata
from datetime import timedelta
from html.parser import HTMLParser

from core.collections_memoria_source import MemoriaSource
from core.collections_repository import stamp, utcnow, CollectionRunCancelled
from core.error_reporting import log_handled_failure
from logging_utils import get_logger

COUNTRIES = {'FR':('france','France','fr_FR'), 'US':('united-states','United States','en_US'),
             'GB':('united-kingdom','United Kingdom','en_GB'), 'DE':('germany','Germany','de_DE'),
             'ES':('spain','Spain','es_ES'), 'IT':('italy','Italy','it_IT'),
             'CA':('canada','Canada','en_CA'), 'BE':('belgium','Belgium','fr_BE'),
             'CH':('switzerland','Switzerland','de_CH')}
from core.collections_streaming_options import EXTRA_COUNTRIES
COUNTRIES.update({code:row[:3] for code,row in EXTRA_COUNTRIES.items()})
PUBLIC_HEADERS = {'User-Agent':'Mozilla/5.0'}


def normalized(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD',str(value or '').casefold()) if not unicodedata.combining(c))
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in value).split())


class PageText(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.lines, self.skipped = [], 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skipped += 1

    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skipped = max(0,self.skipped-1)

    def handle_data(self, data):
        text = ' '.join(data.split())
        if text and not self.skipped: self.lines.append(text)


def netflix_chart(html, country, media_type):
    lines = PageText(html).lines
    category = 'Movies' if media_type=='movie' else 'Shows'
    marker = f'Top 10 {category} in {COUNTRIES[country][1]} overview'.casefold()
    start = next((i for i,line in enumerate(lines) if line.casefold()==marker),None)
    if start is None: raise ValueError('collections.streaming_source_invalid')
    rows, index = [], start+1
    while index < len(lines) and len(rows)<10:
        line = lines[index]
        if line=='Catch the Latest': break
        if re.fullmatch(r'0[1-9]|10',line) and int(line)==len(rows)+1 and index+1<len(lines):
            title = lines[index+1]
            if media_type=='tv':
                title = re.sub(r'\s*:\s*(?:season|saison|staffel|temporada|stagione)\s+\d+.*$','',title,flags=re.I)
            rows.append({'title':title,'rank':int(line)})
            index += 2
            if index<len(lines) and re.fullmatch(r'\d{1,2}',lines[index]): index += 1
        else: index += 1
    if len(rows)!=10: raise ValueError('collections.streaming_source_invalid')
    return rows


def provider_family(provider):
    """Count a service once when it is also sold through channel resellers."""
    code=provider['id']
    aliases={'pva':'prv','plc':'plx','pxp':'plx','mni':'mxp','nfk':'nfx'}
    if code in aliases:return aliases[code]
    name=normalized(provider.get('name'))
    name=re.sub(r' (?:amazon|apple tv) channel$', '',name)
    name=re.sub(r' with ads$', '',name)
    if name in ('netflix','netflix standard','netflix basic','netflix premium'):
        return 'nfx'
    if name in ('paramount plus','paramount plus premium','paramount plus standard','paramount+'):
        return 'pmp'
    return name or code


def merge_charts(rows):
    merged = {}
    for row in rows:
        key = int(row['id'])
        item = merged.setdefault(key,{**row,'sources':[],'ranks_by_source':{},'source_kinds':{},'ranks_by_service':{}})
        provider = row['source']
        if provider not in item['sources']: item['sources'].append(provider)
        item['ranks_by_source'][provider] = min(row['rank'],item['ranks_by_source'].get(provider,row['rank']))
        item['source_kinds'][provider] = row['source_kind']
        family=row.get('source_family',provider)
        item['ranks_by_service'][family]=min(row['rank'],item['ranks_by_service'].get(family,row['rank']))
    for item in merged.values():
        item['buzz_score'] = (100*len(item['ranks_by_service']) + sum(max(0,110-10*r) for r in item['ranks_by_service'].values())
                             + min(float(item.get('popularity') or 0),200)/10)
    return sorted(merged.values(),key=lambda row:(-row['buzz_score'],min(row['ranks_by_source'].values()),row['id']))


class StreamingSource(MemoriaSource):
    def __init__(self, key, language):
        super().__init__(key,language)
        self.diagnostics = []
        self.partial = False

    def failure(self, exc, provider, country, media_type, stage):
        response = getattr(exc,'response',None)
        status = getattr(response,'status_code',None)
        status = status if isinstance(status,int) else None
        detail = {'provider':provider,'country':country,'media_type':media_type,'stage':stage,
                  'http_status':status,'error_type':type(exc).__name__}
        # Only validated identifiers and exception types; never response bodies,
        # credentials, request headers or raw exception strings.
        get_logger('collections.streaming').error(
            'Streaming provider failed | provider=%s | country=%s | media_type=%s | stage=%s | http_status=%s | error_type=%s',
            provider,country,media_type,stage,status,type(exc).__name__)
        log_handled_failure('collections.streaming.provider',level='error')
        return detail

    def cached(self, key, hours, loader):
        key = json.dumps(['streaming-v1',key],sort_keys=True)
        row = self.db.query_one('SELECT data_json FROM collection_discovery_cache WHERE cache_key=? AND updated_at>?',
            (key,stamp(utcnow()-timedelta(hours=hours)))) if self.db else None
        if row: return json.loads(row['data_json'])
        self.heartbeat()
        data = loader()
        if self.db:
            self.db.execute('INSERT INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at',
                (key,json.dumps(data),stamp()))
        return data

    def providers(self, country):
        def load():
            response = self.http.get('https://apis.justwatch.com/content/providers/locale/'+COUNTRIES[country][2],
                headers=PUBLIC_HEADERS,timeout=(10,25))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data,list) or not data: raise ValueError('collections.streaming_source_invalid')
            providers = {}
            for row in data:
                # Ignore services that only sell/rent titles. Keep subscription,
                # free and advertising-supported providers, including local ones.
                if not {'flatrate','free','ads'} & set(row.get('monetization_types') or []): continue
                code = row.get('short_name')
                if not isinstance(code,str) or not re.fullmatch(r'[a-z0-9_]{1,30}',code):
                    raise ValueError('collections.streaming_source_invalid')
                providers[code] = {'id':code,'name':row.get('clear_name') or code}
            if not providers: raise ValueError('collections.streaming_source_invalid')
            return list(providers.values())
        try:
            return self.cached(['providers',country],24,load)
        except CollectionRunCancelled: raise
        except Exception as exc:
            detail = self.failure(exc,'justwatch',country,'all','catalog')
            self.diagnostics = [{'id':'justwatch','name':'JustWatch','state':'error','count':0,'failure':detail}]
            raise

    def justwatch(self, provider, country, media_type):
        # Values have been validated locally; preserve the proven query shape
        # of top_hit_series/justwatch.py instead of assuming GraphQL enum names.
        query = f'''query {{
          popularTitles(country: "{country}", first: 10,
            filter: {{objectTypes: [{"MOVIE" if media_type=='movie' else "SHOW"}], packages: ["{provider}"], monetizationTypes: [FLATRATE, FREE, ADS]}}, sortBy: POPULAR) {{
            edges {{ node {{ objectType content(country: "{country}", language: "{self.language}") {{
              title originalTitle originalReleaseYear externalIds {{ tmdbId imdbId }}
            }} }} }}
          }}
        }}'''
        response = self.http.post('https://apis.justwatch.com/graphql',headers={**PUBLIC_HEADERS,'Content-Type':'application/json'},
            json={'query':query},timeout=(10,25))
        response.raise_for_status()
        data = response.json()
        if data.get('errors'): raise ValueError('collections.streaming_source_invalid')
        edges = (data.get('data') or {}).get('popularTitles',{}).get('edges')
        if not isinstance(edges,list): raise ValueError('collections.streaming_source_invalid')
        rows = []
        for rank,edge in enumerate(edges,1):
            node = edge.get('node') or {}; content = node.get('content') or {}
            expected = 'MOVIE' if media_type=='movie' else 'SHOW'
            if node.get('objectType')!=expected or not content.get('title'):
                raise ValueError('collections.streaming_source_invalid')
            external = content.get('externalIds') or {}
            rows.append({'title':content['title'],'original_title':content.get('originalTitle'),
                         'year':content.get('originalReleaseYear'),'id':external.get('tmdbId'),
                         'imdb_id':external.get('imdbId'),'rank':rank})
        return rows

    def chart(self, provider, country, media_type):
        def load():
            failures = []
            slug = COUNTRIES[country][0]
            if provider=='nfx':
                url = 'https://www.netflix.com/tudum/top10/'+slug+('/tv' if media_type=='tv' else '')
                parser = lambda html:netflix_chart(html,country,media_type)
            else:
                url = None
            if url:
                try:
                    self.heartbeat()
                    response = self.http.get(url,headers=PUBLIC_HEADERS,timeout=(10,25)); response.raise_for_status()
                    return {'items':parser(response.text),'kind':'platform_chart','url':url}
                except CollectionRunCancelled: raise
                except Exception as exc:
                    failures.append(self.failure(exc,provider,country,media_type,'platform_chart'))
            self.heartbeat()
            return {'items':self.justwatch(provider,country,media_type),'kind':'justwatch_popularity',
                    'url':'https://www.justwatch.com/'+country.lower(),'failures':failures}
        return self.cached(['chart',provider,country,media_type,self.language],6,load)

    def original_language(self, media_type, row):
        details = self.cached(['content-language',media_type,row['id']],24,
                              lambda:self.tmdb(f"/{media_type}/{row['id']}"))
        language = details.get('original_language')
        if not isinstance(language,str) or not language:
            raise ValueError('collections.original_language_unknown')
        return language.lower()

    def resolve(self, row, media_type):
        if row.get('id'):
            # JustWatch already supplies a typed TMDb identity. Do not issue
            # up to ten redundant TMDb detail calls per regional provider.
            identifier = str(row['id'])
            if not identifier.isdigit() or int(identifier)<=0:
                raise ValueError('collections.streaming_identity_failed')
            return {'id':int(identifier),'title':row['title'],'year':str(row.get('year') or ''),
                    'imdb_id':row.get('imdb_id'),'popularity':0}
        def load():
            query = {'query':row['title'],'include_adult':'false'}
            if row.get('year'): query['year' if media_type=='movie' else 'first_air_date_year'] = row['year']
            results = self.tmdb('/search/'+media_type,**query).get('results',[])
            names = {normalized(row.get('title')),normalized(row.get('original_title'))}-{''}
            matches = [r for r in results if names & {normalized(r.get(k)) for k in ('title','name','original_title','original_name')}
                       and (not row.get('year') or str(r.get('release_date') or r.get('first_air_date') or '')[:4]==str(row['year']))]
            unique = {r['id']:r for r in matches}
            if len(unique)!=1: raise ValueError('collections.streaming_identity_failed')
            details = next(iter(unique.values()))
            if not isinstance(details.get('id'),int) or details['id']<=0:
                raise ValueError('collections.streaming_identity_failed')
            return {'id':details['id'],'title':details.get('title') or details.get('name') or row['title'],
                    'year':str(details.get('release_date') or details.get('first_air_date') or '')[:4],
                    'popularity':details.get('popularity',0)}
        return self.cached(['identity',media_type,self.language,row.get('id'),row['title'],row.get('year')],24,load)

    def discover(self, country, media_type, platform=None):
        self.partial = False
        if country not in COUNTRIES: raise ValueError('collections.invalid_country')
        providers = self.providers(country)
        if platform:
            providers = [row for row in providers if row['id']==platform]
            if not providers: raise ValueError('collections.streaming_source_invalid')
        resolved, failed = [], False
        self.diagnostics = []
        for provider in providers:
            self.heartbeat()
            diagnostic = {**provider,'state':'error','count':0}
            try:
                chart = self.chart(provider['id'],country,media_type)
                diagnostic.update(source_kind=chart['kind'],url=chart['url'],failures=chart.get('failures',[]))
                identities=None
                try:
                    if chart['kind']=='platform_chart':
                        # A direct chart with ambiguous names falls back to typed IDs.
                        identities=[self.resolve(row,media_type) for row in chart['items']]
                except CollectionRunCancelled: raise
                except ValueError as exc:
                    if chart['kind']!='platform_chart' or str(exc)!='collections.streaming_identity_failed': raise
                    diagnostic['failures'].append(self.failure(exc,provider['id'],country,media_type,'identity'))
                    chart = {'items':self.justwatch(provider['id'],country,media_type),'kind':'justwatch_popularity'}
                    diagnostic.update(source_kind=chart['kind'],url='https://www.justwatch.com/'+country.lower())
                count=0
                family=provider_family(provider)
                # Map aliases to the base service's canonical name as well.
                base=next((p for p in providers if p['id']==family),None)
                if base:family=provider_family(base)
                for index,row in enumerate(chart['items']):
                    try:media=identities[index] if identities is not None else self.resolve(row,media_type)
                    except CollectionRunCancelled:raise
                    except Exception as exc:
                        failed=True
                        diagnostic['identity_skipped']=True
                        diagnostic['failures'].append(self.failure(exc,provider['id'],country,media_type,'identity'))
                        continue
                    resolved.append({**media,'source':provider['id'],'source_family':family,
                                     'rank':row['rank'],'source_kind':chart['kind']})
                    count+=1
                diagnostic.update(state='warning' if diagnostic.get('failures') or count<len(chart['items']) else 'success',count=count)
            except CollectionRunCancelled: raise
            except Exception as exc:
                failed = True
                diagnostic['failure'] = self.failure(exc,provider['id'],country,media_type,'chart_or_identity')
            self.diagnostics.append(diagnostic)
        self.partial = failed
        if failed and not resolved: raise ValueError('collections.streaming_incomplete')
        if not resolved: raise ValueError('collections.streaming_empty')
        return merge_charts(resolved)
