"""Curated public list references and explicit local-library theme selection."""
import json
import random
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from core.collections_repository import CollectionRunCancelled
from core.collections_streaming_source import StreamingSource, normalized, PUBLIC_HEADERS

CATALOG=json.loads((Path(__file__).resolve().parents[1]/'data'/'seasonal_sources.json').read_text(encoding='utf-8'))
THEMES={
 'new_year':['new year','new years eve','nouvel an','silvester','capodanno'],
 'valentine':['valentine','romance','saint valentin','san valentino'],
 'patrick':['saint patrick','st patrick','leprechaun'], 'easter':['easter','paques','ostern','pasqua'],
 'mother':['motherhood','pregnancy','maternite'], 'father':['fatherhood','paternite'],
 'memorial':['military','war veteran'], 'labor':['labor union','labour union','working class'],
 'halloween':['halloween','witch','ghost','vampire','werewolf','haunted house'],
 'veteran':['war veteran','military veteran'], 'thanksgiving':['thanksgiving'],
 'christmas':['christmas','noel','weihnachten','natale','navidad','santa claus'],
 'aapi':['asian american','pacific islander'], 'disabilities':['disability','disabled person'],
 'black_history':['african american','black history','civil rights'],
 'lgbtq':['lgbt','lgbtq','gay','lesbian','transgender','queer'],
 'latinx':['latino','latina','latinx','hispanic'], 'women':['women s rights','womens rights','female empowerment','women in film'],
 'summer':['summer vacation','summer camp','summer holiday','vacances d ete']}
NATIONAL_THEMES={'US':['independence day','fourth of july','july 4','american revolution'],
 'FR':['bastille day','14 juillet','french revolution','revolution francaise'],
 'CA':['canada day','fete du canada'],'BE':['belgian national day','fete nationale belge'],
 'CH':['swiss national day','fete nationale suisse'],'DE':['german reunification','german unity'],
 'IT':['festa della repubblica','italian republic'],'ES':['fiesta nacional','dia de la hispanidad']}


def local_match(row,event,country):
    labels={normalized(value) for value in [*(row.get('labels') or []),*(row.get('tags') or [])]}
    if normalized('seasonal:'+event) in labels or normalized('seasonal:'+event+':'+country) in labels:return True
    genres={normalized(value) for value in row.get('genres') or []}
    if event=='halloween' and genres & {'horror','horreur','horrorfilm','terror'}:return True
    if event=='valentine' and genres & {'romance','romantique','liebesfilm'}:return True
    text=' '+normalized(' '.join(str(row.get(key) or '') for key in ('title','original_title','summary')))+' '
    keywords=[*labels,*[normalized(value) for value in row.get('keywords') or []]]
    terms=NATIONAL_THEMES.get(country,[]) if event=='independence' else THEMES.get(event,[])
    return any(' '+normalized(term)+' ' in text or normalized(term) in keywords for term in terms)


class ListHTML(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True)
        self.scripts=[];self.current=None;self.parts=[];self.films=[];self.next=None
        self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script' and (attrs.get('type')=='application/ld+json' or attrs.get('id')=='__NEXT_DATA__'):
            self.current=True;self.parts=[]
        slug=attrs.get('data-film-slug') or attrs.get('data-item-slug')
        if slug and ('poster' in attrs.get('class','') or attrs.get('data-film-id') or slug.startswith('/film/')):
            if not slug.startswith('/'):slug='/film/'+slug.strip('/')+'/'
            if re.fullmatch(r'/film/[a-zA-Z0-9_-]+/',slug):self.films.append(slug)
        if tag=='a' and ('next' in attrs.get('rel','').split() or 'next' in attrs.get('class','').split()):self.next=attrs.get('href')
    def handle_data(self,data):
        if self.current:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.current:
            self.scripts.append(json.loads(''.join(self.parts)));self.current=None


def imdb_list_ids(text):
    ids=[];total=None
    def walk(value):
        nonlocal total
        if isinstance(value,list):
            for row in value:walk(row)
        elif isinstance(value,dict):
            if value.get('@type')=='ItemList':
                total=value.get('numberOfItems',total)
                for row in value.get('itemListElement',[]):
                    item=row.get('item') or row
                    link=item.get('url') or item.get('@id') or ''
                    match=re.search(r'/title/(tt\d+)',link)
                    if match:ids.append(match[1])
            for key,item in value.items():
                if key in ('titleListItemSearch','titleListItems'):
                    if isinstance(item,dict):
                        total=item.get('total',item.get('totalCount',total))
                        records=item.get('edges',[])
                    else:records=item
                    for record in records:
                        node=record.get('node',record);title=node.get('title',node)
                        identifier=title.get('id')
                        if isinstance(identifier,str) and re.fullmatch(r'tt\d+',identifier):ids.append(identifier)
                else:walk(item)
    for script in ListHTML(text).scripts:walk(script)
    ids=list(dict.fromkeys(ids))
    if not ids or total is not None and int(total)>len(ids):raise ValueError('collections.seasonal_list_incomplete')
    return ids


class SeasonalEventSource(StreamingSource):
    def __init__(self,key,language,*,event,country,mode,inventory,sort,seed):
        super().__init__(key if mode!='local' else 'local-only',language)
        self.event,self.country,self.mode,self.inventory=event,country,mode,inventory
        self.sort,self.seed=sort,seed

    def public(self,url,json_data=False):
        def load():
            self.heartbeat()
            response=self.http.get(url,headers=PUBLIC_HEADERS,timeout=(10,30))
            response.raise_for_status()
            if response.status_code!=200 or not response.content:
                raise requests.HTTPError(response=response)
            if len(response.content)>8_000_000:raise ValueError('collections.seasonal_list_incomplete')
            return response.json() if json_data else response.text
        # Keep compact parsed identities for HTML sources, not hundreds of
        # complete film pages in the database. JSON lists are already compact.
        return self.cached(['seasonal-public-v1',url,json_data],24,load) if json_data else load()

    def imdb(self,list_id,kind):
        ids=self.cached(['seasonal-imdb-list',list_id],24,
            lambda:imdb_list_ids(self.public('https://www.imdb.com/list/'+list_id+'/')))
        result=[]
        for identifier in ids:
            self.heartbeat()
            data=self.cached(['seasonal-imdb-find',identifier,kind,self.language],24*30,
                lambda:self.tmdb('/find/'+identifier,external_source='imdb_id'))
            rows=data.get('movie_results' if kind=='movie' else 'tv_results')
            if not isinstance(rows,list):raise ValueError('collections.seasonal_list_incomplete')
            for row in rows:result.append({**row,'title':row.get('title') or row.get('name'),'imdb_id':identifier})
        return result

    def mdblist(self,url,kind):
        data=self.public(url.rstrip('/')+'/json/',True)
        if not isinstance(data,list):raise ValueError('collections.seasonal_list_incomplete')
        rows=[]
        for row in data:
            actual=row.get('mediatype')
            if actual not in ('movie','show','tv'):raise ValueError('collections.seasonal_list_incomplete')
            if (actual=='movie')!=(kind=='movie'):continue
            identifier=row.get('id')
            if type(identifier) is not int or identifier<=0 or not row.get('title'):
                raise ValueError('collections.seasonal_list_incomplete')
            rows.append({'id':identifier,'title':row['title'],'imdb_id':row.get('imdb_id'),
                         'tvdb_id':row.get('tvdbid'),'release_date':str(row.get('release_year') or '')})
        return rows

    def letterboxd(self,url,kind):
        if kind!='movie':return []
        rows=[];seen=set()
        while url:
            if urlparse(url).hostname!='letterboxd.com' or url in seen or len(seen)>=30:
                raise ValueError('collections.seasonal_list_incomplete')
            seen.add(url)
            def parse_page():
                parsed=ListHTML(self.public(url))
                if not parsed.films:raise ValueError('collections.seasonal_list_incomplete')
                return {'films':list(dict.fromkeys(parsed.films)),'next':parsed.next}
            parsed=self.cached(['seasonal-letterboxd-page',url],24,parse_page)
            for slug in parsed['films']:
                def film_id():
                    text=self.public('https://letterboxd.com'+slug)
                    identifiers=set(re.findall(r'themoviedb\.org/movie/(\d+)',text))
                    if len(identifiers)!=1:raise ValueError('collections.seasonal_list_incomplete')
                    return int(next(iter(identifiers)))
                identifier=self.cached(['seasonal-letterboxd-film',slug],24*30,film_id)
                rows.append({'id':identifier,'title':slug.split('/')[2].replace('-',' ')})
            url=urljoin(url,parsed['next']) if parsed['next'] else None
        return rows

    def keywords(self,terms,kind):
        identifiers=[]
        for term in terms:
            data=self.cached(['seasonal-keyword',term],24*30,lambda:self.tmdb('/search/keyword',query=term))
            identifiers.extend(row['id'] for row in data.get('results',[]) if normalized(row.get('name'))==normalized(term))
        if not identifiers:raise ValueError('collections.seasonal_list_incomplete')
        rows=[]
        for page in range(1,26):
            data=self.cached(['seasonal-discover',kind,identifiers,page,self.language],24,
                lambda:self.tmdb('/discover/'+kind,with_keywords='|'.join(map(str,identifiers)),
                                 include_adult='false',sort_by='popularity.desc',page=page))
            if not isinstance(data.get('results'),list):raise ValueError('collections.seasonal_list_incomplete')
            rows.extend({**row,'title':row.get('title') or row.get('name')} for row in data['results'])
            if page>=data.get('total_pages',1):return rows
        raise ValueError('collections.seasonal_list_incomplete')

    def discover(self,country,kind):
        if kind!='movie':raise ValueError('collections.invalid_library')
        self.partial=False;self.diagnostics=[]
        merged={}
        def add(rows,provider,local=False):
            for row in rows:
                identifier=row.get('id')
                if not local and (type(identifier) is not int or identifier<=0 or not row.get('title')):
                    raise ValueError('collections.seasonal_list_incomplete')
                key=('tmdb',identifier) if identifier else ('local',tuple(row['library_item_ids']))
                item=merged.setdefault(key,{**row,'id':identifier,'sources':[],'ranks_by_source':{},'source_kinds':{},'buzz_score':0})
                if provider not in item['sources']:item['sources'].append(provider)
                item['source_kinds'][provider]='seasonal_local' if local else 'seasonal_web'
                if local:item['library_item_ids']=list(dict.fromkeys([*item.get('library_item_ids',[]),*row['library_item_ids']]))
        if self.mode in ('local','both'):
            rows=[]
            inventory=self.inventory()
            incomplete=any(not any(key in row for key in ('genres','labels','tags','summary')) for row in inventory)
            for row in inventory:
                self.heartbeat()
                if local_match(row,self.event,country):
                    identifier=str(row.get('tmdb') or '')
                    rows.append({**row,'id':int(identifier) if identifier.isdigit() and int(identifier)>0 else None,
                                 'library_item_ids':[row['id']]})
            add(rows,'library',True)
            diagnostic={'id':'library','name':'Library','state':'success','count':len(rows)}
            if incomplete:
                self.partial=True
                try:raise ValueError('collections.inventory_required')
                except ValueError as exc:diagnostic['failure']=self.failure(exc,'library',country,kind,'seasonal_metadata')
                diagnostic['state']='warning'
            self.diagnostics.append(diagnostic)
        if self.mode in ('web','both'):
            spec=CATALOG['events'][self.event]
            builders=[]
            # The configured Independence lists are specifically US-themed. Other
            # countries use their own theme instead of relabelling July 4 films.
            if self.event!='independence' or country=='US':
                for identifier in spec.get('imdb',[]):builders.append(('imdb_'+identifier,lambda i=identifier:self.imdb(i,kind)))
                for url in spec.get('mdblist',[]):builders.append(('mdblist',lambda u=url:self.mdblist(u,kind)))
                for url in spec.get('letterboxd',[]):builders.append(('letterboxd',lambda u=url:self.letterboxd(u,kind)))
                if kind=='movie':
                    for identifier in spec.get('tmdb_collection',[]):
                        builders.append(('tmdb_collection_'+str(identifier),lambda i=identifier:self.cached(['seasonal-collection',i,self.language],24,lambda:self.tmdb('/collection/'+str(i))).get('parts',[])))
                    for identifier in spec.get('tmdb_movie',[]):
                        builders.append(('tmdb_movie_'+str(identifier),lambda i=identifier:[self.cached(['seasonal-movie',i,self.language],24,lambda:self.tmdb('/movie/'+str(i)))]))
            terms=NATIONAL_THEMES.get(country,[]) if self.event=='independence' else spec.get('keywords',[])
            if terms:builders.append(('tmdb_keywords',lambda:self.keywords(terms,kind)))
            for provider,loader in builders:
                self.heartbeat()
                diagnostic={'id':provider,'name':provider,'state':'error','count':0,'event':self.event}
                try:
                    rows=loader();add(rows,provider)
                    diagnostic.update(state='success',count=len(rows))
                except CollectionRunCancelled:raise
                except Exception as exc:
                    self.partial=True
                    diagnostic['failure']=self.failure(exc,provider,country,kind,'seasonal_'+self.event)
                self.diagnostics.append(diagnostic)
        rows=list(merged.values())
        if self.partial and not rows:raise ValueError('collections.seasonal_sources_unavailable')
        if self.sort=='daily_random':random.Random(self.seed).shuffle(rows)
        elif self.sort=='popularity':rows.sort(key=lambda row:float(row.get('popularity') or 0),reverse=True)
        else:rows.sort(key=lambda row:(str(row.get('release_date') or row.get('first_air_date') or ''),str(row['id'])),reverse=True)
        return rows
