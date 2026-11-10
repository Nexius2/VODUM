"""Shared streaming source utilities and official regional Netflix charts."""
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


def merge_charts(rows, *, regional=False):
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
        ranks = item['ranks_by_service'].values()
        item['buzz_score'] = sum(max(0,110-10*r) for r in ranks)
        if not regional:
            item['buzz_score'] += 100*len(ranks) + min(float(item.get('popularity') or 0),200)/10
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

    def original_language(self, media_type, row):
        details = self.cached(['content-language',media_type,row['id']],24,
                              lambda:self.tmdb(f"/{media_type}/{row['id']}"))
        language = details.get('original_language')
        if not isinstance(language,str) or not language:
            raise ValueError('collections.original_language_unknown')
        return language.lower()

    def resolve(self, row, media_type):
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

    def discover(self, country, media_type):
        self.partial = False
        if country not in COUNTRIES: raise ValueError('collections.invalid_country')
        slug = COUNTRIES[country][0]
        url = 'https://www.netflix.com/tudum/top10/'+slug+('/tv' if media_type=='tv' else '')
        diagnostic = {'id':'nfx','name':'Netflix','source_kind':'platform_chart',
                      'url':url,'state':'error','count':0,'failures':[]}
        self.diagnostics = [diagnostic]

        def load():
            response = self.http.get(url,headers=PUBLIC_HEADERS,timeout=(10,25))
            response.raise_for_status()
            return netflix_chart(response.text,country,media_type)

        try:
            chart = self.cached(['netflix-official-chart-v1',country,media_type],6,load)
        except CollectionRunCancelled: raise
        except Exception as exc:
            diagnostic['failure'] = self.failure(exc,'nfx',country,media_type,'platform_chart')
            raise ValueError('collections.streaming_incomplete') from exc
        resolved = []
        for row in chart:
            self.heartbeat()
            try:
                media = self.resolve(row,media_type)
            except CollectionRunCancelled: raise
            except Exception as exc:
                self.partial = True
                diagnostic['identity_skipped'] = True
                diagnostic['failures'].append(self.failure(exc,'nfx',country,media_type,'identity'))
                continue
            resolved.append({**media,'source':'nfx','rank':row['rank'],'source_kind':'platform_chart'})
        if not resolved: raise ValueError('collections.streaming_incomplete')
        diagnostic.update(state='warning' if self.partial else 'success',count=len(resolved))
        return merge_charts(resolved,regional=True)
