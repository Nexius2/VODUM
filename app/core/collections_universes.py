"""Typed, complete membership sources for the curated film franchises."""
import json
import re
from pathlib import Path
from requests import RequestException
from core.collections_universes_catalog import UNIVERSES
from core.collections_repository import CollectionRunCancelled


class UnresolvedFranchiseIdentity(ValueError):
    """A list entry has no unambiguous identity in the target TMDb catalog."""


class UniverseLists:
    def imdb(self, list_id, kind, *, include_video=False, include_short=False, include_special=False, supplements_only=False):
        if not re.fullmatch(r'ls[0-9]+', list_id):
            raise ValueError('collections.franchises_source_failed')

        allowed = {'movie','tvMovie'} if kind == 'movie' else {'tvSeries','tvMiniSeries'}
        if kind == 'movie':
            if include_video: allowed.add('video')
            if include_short: allowed.update(('short','tvShort'))
            if include_special: allowed.add('tvSpecial')
            if supplements_only: allowed.discard('movie')

        def load():
            rows = []
            seen = set()
            cursors = set()
            cursor = None
            expected = None
            processed = 0
            for _ in range(100):
                self.heartbeat()
                query = '''query {
                  list(id: LIST_ID) {
                    items(first: 250, after: CURSOR) {
                      total pageInfo { hasNextPage endCursor }
                      edges { node { item { ... on Title {
                        id titleText { text } titleType { id } releaseYear { year }
                      } } } }
                    }
                  }
                }'''.replace('LIST_ID', json.dumps(list_id)).replace('CURSOR', json.dumps(cursor))
                response = self.http.post('https://api.graphql.imdb.com/',
                    headers={'Content-Type':'application/json','x-imdb-client-name':'imdb-web-next'},
                    json={'query':query},timeout=(10,30))
                response.raise_for_status()
                payload = response.json()
                if response.status_code != 200 or not isinstance(payload,dict) or payload.get('errors'):
                    raise ValueError('collections.franchises_source_failed')
                section = ((payload.get('data') or {}).get('list') or {}).get('items') or {}
                total = section.get('total')
                if type(total) is not int or total <= 0 or (expected is not None and total != expected):
                    raise ValueError('collections.franchises_source_failed')
                expected = total
                edges = section.get('edges')
                page = section.get('pageInfo') or {}
                if not isinstance(edges,list) or not edges or type(page.get('hasNextPage')) is not bool:
                    raise ValueError('collections.franchises_source_failed')
                for edge in edges:
                    item = ((edge.get('node') or {}).get('item') or {})
                    identifier = item.get('id')
                    if not re.fullmatch(r'tt[0-9]+',str(identifier or '')):
                        raise ValueError('collections.franchises_source_failed')
                    processed += 1
                    if identifier in seen:
                        continue
                    seen.add(identifier)
                    title_type = (item.get('titleType') or {}).get('id')
                    if not title_type:
                        raise ValueError('collections.franchises_source_failed')
                    if title_type in allowed:
                        rows.append(identifier)
                if not page['hasNextPage']:
                    if processed != expected:
                        raise ValueError('collections.franchises_source_failed')
                    if not rows:
                        raise ValueError('collections.franchises_source_failed')
                    return rows
                cursor = page.get('endCursor')
                if not isinstance(cursor,str) or not cursor or cursor in cursors:
                    raise ValueError('collections.franchises_source_failed')
                cursors.add(cursor)
            raise ValueError('collections.franchises_source_failed')

        try:
            ids = self.cached(['franchise-imdb-graphql-v4',list_id,kind,include_video,include_short,include_special,supplements_only],24,load)
        except CollectionRunCancelled:raise
        except (RequestException,ValueError) as exc:
            snapshot=json.loads((Path(__file__).resolve().parents[1]/'data'/'franchise_list_snapshot.json').read_text(encoding='utf-8'))
            saved=snapshot['lists'].get(list_id)
            if kind!='movie' or not saved:raise
            types=saved.get('title_types')
            if types:
                ids=[identifier for identifier in saved['imdb_ids'] if types.get(identifier) in allowed]
            else:
                if saved['include_video']!=include_video or include_short or include_special or supplements_only:raise
                ids=saved['imdb_ids']
            if not ids:raise
            self.partial=True
            self.diagnostics.append({'id':list_id,'name':'IMDb · '+list_id,'state':'warning',
                'count':len(ids),'snapshot_date':snapshot['retrieved_at'],
                'failure':{'provider':'imdb','country':'franchises','media_type':kind,
                           'stage':'members','error_type':type(exc).__name__,'reason':'franchise_snapshot'}})
        return self.resolve_franchise_ids(ids,kind,list_id)

    def resolve_franchise_ids(self, ids, kind, source_id):
        rows = []
        unresolved = []
        network_failures=0
        for identifier in ids:
            self.heartbeat()
            local=getattr(self,'local_franchise_media',{}).get(identifier)
            if local:
                rows.append({**local,'imdb_id':identifier})
                continue
            def resolve(value=identifier):
                if getattr(self,'franchise_identity_network_blocked',False):
                    raise UnresolvedFranchiseIdentity('collections.franchises_source_failed')
                data = self.tmdb('/find/'+value,external_source='imdb_id')
                matches = data.get('movie_results' if kind=='movie' else 'tv_results')
                if (not isinstance(matches,list) or len(matches)!=1 or not isinstance(matches[0],dict)
                        or type(matches[0].get('id')) is not int or matches[0]['id']<=0
                        or not (matches[0].get('title') or matches[0].get('name'))):
                    raise UnresolvedFranchiseIdentity('collections.franchises_source_failed')
                return matches[0]
            try:
                # Only successful mappings are cached. Empty old lookups must
                # not block a film for a month after metadata is corrected.
                media = self.cached(['franchise-imdb-identity-v2',identifier,kind,self.language],24*30,resolve)
            except RequestException:
                network_failures+=1
                if network_failures>=3:self.franchise_identity_network_blocked=True
                unresolved.append(identifier)
                continue
            except UnresolvedFranchiseIdentity:
                unresolved.append(identifier)
                continue
            network_failures=0
            rows.append({**media,'imdb_id':identifier})
        if unresolved:
            self.partial = True
            self.diagnostics.append({'id':'franchise_identity_'+source_id,'name':'TMDb · '+', '.join(unresolved),
                'state':'warning','count':len(unresolved),'unresolved_imdb_ids':unresolved,
                'failure':{'provider':'tmdb','country':'franchises','media_type':kind,'stage':'identity',
                           'error_type':'UnresolvedIdentity','reason':'franchise_imdb_identity_unresolved'}})
        if not rows:
            raise ValueError('collections.franchises_source_failed')
        return rows

    def universe_groups(self, kind):
        return [{'key':'universe_v2_'+key,'title':spec['title'],'universe':key}
                for key,spec in UNIVERSES.items() if kind in spec['media_types']]

    def universe_members(self, key, kind):
        spec = UNIVERSES[key]
        if kind not in spec['media_types']:
            raise ValueError('collections.invalid_library')
        provider = spec['provider']
        if provider == 'imdb':
            rows = self.imdb(spec['list'].rstrip('/').rsplit('/',1)[-1],kind,include_video=spec.get('include_video',False),include_short=spec.get('include_short',False),include_special=spec.get('include_special',False))
        elif provider == 'tmdb_collection':
            def load():
                collection = self.tmdb('/collection/'+str(spec['collection']))
                rows = collection.get('parts')
                if collection.get('id') != spec['collection'] or not isinstance(rows,list) or not rows:
                    raise ValueError('collections.franchises_source_failed')
                rows = list(rows)
                for identifier in spec.get('movies',[]):
                    self.heartbeat()
                    movie = self.tmdb('/movie/'+str(identifier))
                    if movie.get('id') != identifier or not movie.get('title'):
                        raise ValueError('collections.franchises_source_failed')
                    rows.append(movie)
                # Validate before caching: incomplete membership must never remove films.
                if any(type(row.get('id')) is not int or row['id'] <= 0 or not row.get('title') for row in rows):
                    raise ValueError('collections.franchises_source_failed')
                if not set(spec.get('required_movies',[])).issubset({row['id'] for row in rows}):
                    raise ValueError('collections.franchises_source_failed')
                return rows
            rows = self.cached(['franchise-tmdb-collection-v1',spec['collection'],spec.get('movies',[]),spec.get('required_movies',[]),self.language],24,load)
        elif provider == 'imdb_lists':
            rows=[]
            for list_id in spec['lists']:
                try:
                    rows.extend(self.imdb(list_id,kind,include_video=spec.get('include_video',False),include_short=spec.get('include_short',False),include_special=spec.get('include_special',False)))
                except CollectionRunCancelled:
                    raise
                except Exception as exc:
                    self.partial=True
                    self.diagnostics.append({'id':list_id,'name':'IMDb · '+list_id,'state':'warning',
                        'failure':{'provider':'imdb','country':'franchises','media_type':kind,
                                   'stage':'members','error_type':type(exc).__name__}})
            if not rows:
                raise ValueError('collections.franchises_source_failed')
        else:
            raise ValueError('collections.franchises_source_failed')
        for list_id in spec.get('supplement_lists',[]):
            try:
                rows.extend(self.imdb(list_id,kind,include_video=True,include_short=True,include_special=True,supplements_only=True))
            except CollectionRunCancelled:
                raise
            except Exception as exc:
                self.partial=True
                self.diagnostics.append({'id':list_id,'name':'IMDb · '+list_id,'state':'warning',
                    'failure':{'provider':'imdb','country':'franchises','media_type':kind,
                               'stage':'supplements','error_type':type(exc).__name__}})
        if spec.get('supplement_imdb_ids'):
            try:
                rows.extend(self.resolve_franchise_ids(spec['supplement_imdb_ids'],kind,'supplements_'+key))
            except CollectionRunCancelled:
                raise
            except Exception as exc:
                self.partial=True
                self.diagnostics.append({'id':'supplements_'+key,'name':spec['title']+' · IMDb','state':'warning',
                    'failure':{'provider':'imdb','country':'franchises','media_type':kind,
                               'stage':'supplements','error_type':type(exc).__name__}})
        result = []
        seen = set()
        for row in rows:
            identifier = row.get('id')
            title = row.get('title') or row.get('name')
            if type(identifier) is not int or identifier<=0 or not title:
                raise ValueError('collections.franchises_source_failed')
            if identifier in seen:
                continue
            seen.add(identifier)
            date = row.get('release_date') or row.get('first_air_date') or ''
            result.append({**row,'title':title,'year':str(date)[:4],
                'sources':['franchise_universe'],'source_kinds':{'franchise_universe':provider},
                'ranks_by_source':{'franchise_universe':len(result)+1},'buzz_score':0})
        result.sort(key=lambda row:(row.get('release_date') or row.get('first_air_date') or '9999',row['id']))
        return spec['title'],None,result
