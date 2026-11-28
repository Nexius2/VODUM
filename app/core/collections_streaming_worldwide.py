"""Global and continental subscription availability and popularity via TMDb.

Adapted from the supplied worldwide movie collectors and worldwide TV script.
Never substitute a regional provider catalogue for a worldwide chart.
"""
from core.collections_streaming_source import StreamingSource, merge_charts
from core.collections_repository import CollectionRunCancelled

# Subscription offers are checked against these markets, never production origin.
CONTINENT_MARKETS = {
    'africa': 'ZA:south-africa EG:egypt NG:nigeria KE:kenya MA:morocco',
    'americas': 'US:united-states CA:canada MX:mexico BR:brazil AR:argentina CL:chile CO:colombia PE:peru EC:ecuador UY:uruguay VE:venezuela CR:costa-rica PA:panama DO:dominican-republic GT:guatemala BO:bolivia PY:paraguay HN:honduras SV:el-salvador NI:nicaragua',
    'asia': 'JP:japan KR:south-korea IN:india ID:indonesia TH:thailand PH:philippines MY:malaysia SG:singapore VN:vietnam TW:taiwan HK:hong-kong PK:pakistan BD:bangladesh LK:sri-lanka SA:saudi-arabia AE:united-arab-emirates IL:israel TR:turkey',
    'europe': 'FR:france GB:united-kingdom DE:germany ES:spain IT:italy BE:belgium CH:switzerland AT:austria NL:netherlands PT:portugal IE:ireland PL:poland CZ:czech-republic SK:slovakia HU:hungary RO:romania BG:bulgaria GR:greece HR:croatia SI:slovenia RS:serbia UA:ukraine SE:sweden NO:norway DK:denmark FI:finland IS:iceland EE:estonia LV:latvia LT:lithuania',
    'oceania': 'AU:australia NZ:new-zealand',
}
CONTINENT_MARKETS = {region:dict(pair.split(':') for pair in markets.split())
                     for region,markets in CONTINENT_MARKETS.items()}


class WorldwideStreamingSource(StreamingSource):
    def global_trends(self, media_type, *, region="worldwide"):
        """Script-style popularity, filtered by subscription offers worldwide.

        Unlike the reference script's default US region, every country in the
        official offer response is considered. No HTML chart is required.
        """
        rows, self.trend_failures, seen = [], [], set()
        for page in range(1,6):
            self.heartbeat()
            try:
                def load():
                    params={'sort_by':'popularity.desc','include_adult':'false','page':page}
                    if media_type=='movie':params['include_video']='false'
                    return self.tmdb('/discover/'+media_type,**params)
                data = self.cached(['worldwide-popularity-list-v3',media_type,self.language,page],6,load)
            except CollectionRunCancelled:raise
            except Exception as exc:
                if page==1:raise
                self.trend_failures.append(self.failure(exc,'tmdb_worldwide','worldwide',media_type,'pagination'))
                break
            candidates = data.get('results')
            if not isinstance(candidates,list) or (page==1 and not candidates):
                raise ValueError('collections.streaming_source_invalid')
            for offset,media in enumerate(candidates,1):
                self.heartbeat()
                rank = (page-1)*20+offset
                identifier = media.get('id')
                title = media.get('title') or media.get('name')
                released = media.get('release_date') or media.get('first_air_date')
                if type(identifier) is not int or identifier<=0 or not title:
                    raise ValueError('collections.streaming_source_invalid')
                if identifier in seen:continue
                seen.add(identifier)
                if media.get('adult'):
                    continue
                try:
                    offers = self.cached(['worldwide-offers',media_type,identifier],6,
                        lambda:self.tmdb(f'/{media_type}/{identifier}/watch/providers'))
                    countries = offers.get('results')
                    if not isinstance(countries,dict):
                        raise ValueError('collections.streaming_source_invalid')
                except CollectionRunCancelled: raise
                except Exception as exc:
                    self.trend_failures.append({**self.failure(exc,'tmdb_worldwide','worldwide',media_type,'availability'),
                                                'tmdb_id':identifier})
                    continue
                markets=countries.items() if region=='worldwide' else ((code,row) for code,row in countries.items() if code in CONTINENT_MARKETS[region])
                if not any(isinstance(row,dict) and row.get('flatrate') for _,row in markets):
                    continue
                rows.append({'id':identifier,'title':title,'year':str(released or '')[:4],
                             'popularity':media.get('popularity',0),'rank':rank})
            # Refill AFTER streaming availability checks, instead of reducing a
            # single page of 20 cinema/streaming candidates to a few entries.
            # Keep the bounded candidate pool for the publisher to fill its
            # configured limit AFTER matching the local library.
            total_pages=data.get('total_pages',1)
            if not candidates or type(total_pages) is not int or page>=total_pages:break
        return rows

    def discover(self, country, media_type, platform=None):
        if country not in ('worldwide',*CONTINENT_MARKETS) or media_type not in ('movie','tv'):
            raise ValueError('collections.invalid_configuration')
        if platform not in (None,'tmdb_worldwide'):
            raise ValueError('collections.streaming_source_invalid')
        self.diagnostics, self.partial = [], False
        identifier='tmdb_worldwide' if country=='worldwide' else 'tmdb_'+country
        kind='worldwide_tmdb_streaming' if country=='worldwide' else 'continent_tmdb_streaming'
        diagnostic={'id':identifier,'name':'TMDb Worldwide' if country=='worldwide' else 'TMDb · '+country,
                    'region':country,'source_kind':kind,'ranking':'tmdb_popularity_desc',
                    'state':'error','count':0,'failures':[],
                    'url':'https://www.themoviedb.org/discover/'+media_type}
        self.diagnostics.append(diagnostic)
        try:
            items=self.global_trends(media_type) if country=='worldwide' else self.global_trends(media_type,region=country)
            diagnostic['failures']=getattr(self,'trend_failures',[])
            self.partial=bool(diagnostic['failures'])
            diagnostic.update(count=len(items),state='warning' if self.partial else 'success')
        except CollectionRunCancelled:raise
        except Exception as exc:
            self.partial=True
            diagnostic['failure']=self.failure(exc,identifier,country,media_type,'availability')
            raise ValueError('collections.streaming_incomplete') from exc
        if not items:
            raise ValueError('collections.streaming_incomplete' if self.partial else 'collections.streaming_empty')
        resolved=[{**row,'source':identifier,'source_kind':kind} for row in items]
        rows=merge_charts(resolved)
        for row in rows:row['buzz_score']=float(row.get('popularity') or 0)
        return sorted(rows,key=lambda row:(-row['buzz_score'],' '.join(row['title'].strip().lower().split()),row['id']))
