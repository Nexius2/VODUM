"""Read full IMDb charts, resolve typed identities, reuse owned publication/Arr."""
import json
import re
from requests import HTTPError
from html.parser import HTMLParser

from core.collections_imdb_catalog import CHARTS, imdb_collection_name
from core.collections_repository import CollectionRunCancelled
from core.collections_streaming_source import StreamingSource
from core.collections_streaming import run_streaming_country
from core.collections_media import media_adapter


class ChartScripts(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.kind=None;self.parts=[];self.scripts=[]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='script' and (attrs.get('id')=='__NEXT_DATA__' or attrs.get('type')=='application/ld+json'):
            self.kind=attrs.get('id') or 'ld';self.parts=[]

    def handle_data(self, data):
        if self.kind:self.parts.append(data)

    def handle_endtag(self, tag):
        if tag=='script' and self.kind:
            try:self.scripts.append((self.kind,json.loads(''.join(self.parts))))
            except (ValueError,TypeError):pass
            self.kind=None


class ChartItems(HTMLParser):
    """Fallback limited to actual IMDb chart cards, excluding navigation links."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.row=None;self.heading=False;self.rows=[];self.li_depth=0;self.ranking=False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='li' and 'ipc-metadata-list-summary-item' in attrs.get('class','').split():
            self.row={'title':'','imdb_id':None};self.heading=False;self.li_depth=0
        if self.row is None:return
        if tag=='li':self.li_depth+=1
        if attrs.get('data-testid')=='title-list-item-ranking':self.ranking=True
        if tag=='a' and 'ipc-title-link-wrapper' in attrs.get('class','').split():
            match=re.match(r'^/(?:[a-z]{2}(?:-[A-Z]{2})?/)?title/(tt[0-9]+)(?:/|$)',attrs.get('href',''))
            if match:self.row['imdb_id']=match[1]
        if tag in ('h3','h4'):self.heading=True

    def handle_data(self, data):
        if self.row is not None and self.heading:self.row['title']+=data
        if self.row is not None and self.ranking:
            rank=re.fullmatch(r'\s*#(\d+)\s*',data)
            if rank:self.row['rank']=int(rank[1])

    def handle_endtag(self, tag):
        if tag in ('h3','h4'):self.heading=False
        if tag=='div':self.ranking=False
        if tag=='li' and self.row is not None:
            self.li_depth-=1
            if self.li_depth:return
            title=self.row['title'].strip()
            ranked=re.match(r'^(\d+)[. ]+(.+)$',title)
            self.row.update(rank=int(ranked[1]) if ranked else self.row.get('rank',len(self.rows)+1),
                            title=ranked[2] if ranked else title,year='')
            self.rows.append(self.row);self.row=None


def parse_imdb_chart(html, expected, media_type):
    """Never use arbitrary title links, recommendations, or a truncated top 25."""
    scripts=ChartScripts(html).scripts
    for kind,data in scripts:
        if kind!='__NEXT_DATA__':continue
        props=data.get('props',{}).get('pageProps',{}) if isinstance(data,dict) else {}
        for root in (props.get('pageData',{}),props):
            if not isinstance(root,dict):continue
            for section in (root.get('chartTitles'),(root.get('mainColumnData') or {}).get('chartTitles')):
                edges=section.get('edges') if isinstance(section,dict) else None
                if not isinstance(edges,list):continue
                rows=[]
                for rank,edge in enumerate(edges,1):
                    node=edge.get('node',{})
                    title_type=(node.get('titleType') or {}).get('id')
                    if title_type and title_type not in (('tvSeries','tvMiniSeries') if media_type=='tv' else ('movie',)):
                        raise ValueError('collections.imdb_source_invalid')
                    rows.append({'imdb_id':node.get('id'),'title':(node.get('titleText') or {}).get('text'),
                                 'year':(node.get('releaseYear') or {}).get('year'),'rank':edge.get('currentRank',rank)})
                return validated_rows(rows,expected)
    for kind,data in scripts:
        if kind!='ld':continue
        documents=data if isinstance(data,list) else [data]
        for document in documents:
            if not isinstance(document,dict):continue
            lists=[document,*document.get('@graph',[])]
            for section in lists:
                if not isinstance(section,dict) or section.get('@type')!='ItemList':continue
                rows=[]
                for index,entry in enumerate(section.get('itemListElement',[]),1):
                    item=entry.get('item') or {}
                    if not isinstance(item,dict):raise ValueError('collections.imdb_source_invalid')
                    url=item.get('url') or item.get('@id') or ''
                    match=re.fullmatch(r'(?:https://(?:www\.)?imdb\.com)?/(?:[a-z]{2}(?:-[A-Z]{2})?/)?title/(tt[0-9]+)/?(?:\?[^#]*)?',url)
                    schema_type=item.get('@type')
                    if schema_type and schema_type not in (('TVSeries','TVMiniSeries') if media_type=='tv' else ('Movie',)):
                        raise ValueError('collections.imdb_source_invalid')
                    rows.append({'imdb_id':match[1] if match else None,'title':item.get('name'),
                                 'year':str(item.get('datePublished') or '')[:4],'rank':entry.get('position',index)})
                return validated_rows(rows,expected)
    return validated_rows(ChartItems(html).rows,expected)


def validated_rows(rows, expected):
    if len(rows)!=expected or any(not re.fullmatch(r'tt[0-9]+',str(row.get('imdb_id') or ''))
            or not isinstance(row.get('title'),str) or not row['title'].strip()
            or type(row.get('rank')) is not int for row in rows):
        raise ValueError('collections.imdb_source_invalid')
    if len({row['imdb_id'] for row in rows})!=expected or {row['rank'] for row in rows}!=set(range(1,expected+1)):
        raise ValueError('collections.imdb_source_invalid')
    return sorted(rows,key=lambda row:row['rank'])


GRAPHQL_URL = 'https://api.graphql.imdb.com/'
GRAPHQL_CHARTS = {
    'top': 'TOP_RATED_MOVIES', 'toptv': 'TOP_RATED_TV_SHOWS',
    'moviemeter': 'MOST_POPULAR_MOVIES', 'tvmeter': 'MOST_POPULAR_TV_SHOWS',
    'top_english': 'TOP_RATED_ENGLISH_MOVIES', 'bottom': 'LOWEST_RATED_MOVIES',
    'india': 'TOP_RATED_INDIAN_MOVIES', 'tamil': 'TOP_RATED_TAMIL_MOVIES',
    'telugu': 'TOP_RATED_TELUGU_MOVIES', 'malayalam': 'TOP_RATED_MALAYALAM_MOVIES',
}


class IMDbSource(StreamingSource):
    def chart(self, chart):
        if chart not in CHARTS:
            raise ValueError('collections.imdb_invalid_chart')
        media_type, _, count = CHARTS[chart]

        def load():
            self.heartbeat()
            fields = 'id titleText { text } titleType { id } releaseYear { year }'
            if chart == 'boxoffice':
                query = '{ boxOfficeWeekendChart(limit: %d) { entries { title { %s } } } }' % (count, fields)
            else:
                query = '{ chartTitles(chart: { chartType: %s }, first: %d) { edges { node { %s } } total } }' % (GRAPHQL_CHARTS[chart], count, fields)
            response = self.http.post(
                GRAPHQL_URL,
                headers={'Content-Type': 'application/json', 'x-imdb-client-name': 'imdb-web-next'},
                json={'query': query}, timeout=(10, 30),
            )
            response.raise_for_status()
            if response.status_code != 200:
                raise HTTPError('collections.imdb_source_unavailable', response=response)
            payload = response.json()
            # GraphQL may return HTTP 200 with errors or partial data.
            if not isinstance(payload, dict) or payload.get('errors'):
                raise ValueError('collections.imdb_source_invalid')
            data = payload.get('data')
            if not isinstance(data, dict):
                raise ValueError('collections.imdb_source_invalid')
            section = data.get('boxOfficeWeekendChart' if chart == 'boxoffice' else 'chartTitles')
            if not isinstance(section, dict):
                raise ValueError('collections.imdb_source_invalid')
            entries = section.get('entries' if chart == 'boxoffice' else 'edges')
            if not isinstance(entries, list):
                raise ValueError('collections.imdb_source_invalid')
            rows = []
            for rank, entry in enumerate(entries, 1):
                node = entry.get('title' if chart == 'boxoffice' else 'node') if isinstance(entry, dict) else None
                if not isinstance(node, dict):
                    raise ValueError('collections.imdb_source_invalid')
                allowed = ('tvSeries', 'tvMiniSeries') if media_type == 'tv' else ('movie',)
                # IMDb's popular movie chart includes shorts and TV movies.
                # Preserve its official 100-title ranking, including these films.
                if chart == 'moviemeter':
                    allowed = (*allowed, 'short', 'tvMovie')
                if (node.get('titleType') or {}).get('id') not in allowed:
                    raise ValueError('collections.imdb_source_invalid')
                rows.append({'imdb_id': node.get('id'), 'title': (node.get('titleText') or {}).get('text'),
                             'year': (node.get('releaseYear') or {}).get('year'), 'rank': rank})
            return validated_rows(rows, count)

        return self.cached(['imdb-chart-graphql-v1', chart], 6, load)

    def identity(self, row, media_type):
        def load():
            data=self.tmdb('/find/'+row['imdb_id'],external_source='imdb_id')
            matches=data.get('movie_results' if media_type=='movie' else 'tv_results')
            if not isinstance(matches,list) or len(matches)!=1:
                raise ValueError('collections.streaming_identity_failed')
            media=matches[0]
            if type(media.get('id')) is not int or media['id']<=0:
                raise ValueError('collections.streaming_identity_failed')
            return {'id':media['id'],'title':media.get('title') or media.get('name') or row['title'],
                    'year':str(media.get('release_date') or media.get('first_air_date') or row.get('year') or '')[:4],
                    'imdb_id':row['imdb_id'],'popularity':media.get('popularity',0)}
        return self.cached(['imdb-identity-v1',row['imdb_id'],media_type,self.language],24,load)

    def discover(self, chart, media_type):
        if chart not in CHARTS or CHARTS[chart][0]!=media_type:
            raise ValueError('collections.imdb_invalid_chart')
        self.partial=False
        diagnostic={'id':'imdb','name':imdb_collection_name(chart,self.language),'state':'error','count':0,
                    'source_kind':'imdb_chart','url':'https://www.imdb.com/'+CHARTS[chart][1],'failures':[]}
        self.diagnostics=[diagnostic]
        try:rows=self.chart(chart)
        except CollectionRunCancelled:raise
        except Exception as exc:
            diagnostic['failure']=self.failure(exc,'imdb',chart,media_type,'chart')
            code = 'collections.imdb_source_invalid' if isinstance(exc,ValueError) and str(exc)=='collections.imdb_source_invalid' else 'collections.imdb_source_unavailable'
            raise ValueError(code) from exc
        resolved=[]
        for row in rows:
            self.heartbeat()
            try:media=self.identity(row,media_type)
            except CollectionRunCancelled:raise
            except Exception as exc:
                self.partial=True
                diagnostic['failures'].append(self.failure(exc,'imdb',chart,media_type,'identity'))
                continue
            resolved.append({**media,'rank':row['rank'],'sources':['imdb'],
                             'ranks_by_source':{'imdb':row['rank']},'source_kinds':{'imdb':'imdb_chart'},
                             'buzz_score':100000-row['rank']})
        diagnostic.update(count=len(resolved),state='warning' if self.partial else 'success')
        if not resolved:raise ValueError('collections.streaming_incomplete')
        return resolved


def run_imdb(db, instance, *, kind='sync', heartbeat=lambda:None, source_factory=IMDbSource, adapter_factory=media_adapter):
    config=json.loads(instance['config_json'])
    chart=config.get('imdb_chart','top')
    title=imdb_collection_name(chart,config['language'])
    scoped={**config,'country':chart}
    return run_streaming_country(db,{**instance,'config_json':json.dumps(scoped)},kind=kind,
        heartbeat=heartbeat,source_factory=source_factory,adapter_factory=adapter_factory,
        title_override=title,object_key_override='imdb',poster_key_override='imdb_'+chart)
