"""Typed membership from VODUM lists; TMDb is only used for media resolution."""
from requests import RequestException
from core.collections_repository import CollectionRunCancelled
from core.collections_franchise_lists import definitions,list_items


class UnresolvedFranchiseIdentity(ValueError):
    pass


class UniverseLists:
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

    def universe_groups(self,kind):
        return [{'key':'universe_v2_'+row['id'],'title':row['name'],'universe':row['id']}
                for row in definitions(getattr(self,'db',None)) if row['enabled']]

    def universe_members(self,key,kind):
        definition=next(row for row in definitions(getattr(self,'db',None)) if row['id']==key)
        items=list_items(getattr(self,'db',None),key,kind)
        imdb=[row['external_id'] for row in items if row['provider']=='imdb']
        rows=[]
        if imdb:
            try:rows=self.resolve_franchise_ids(imdb,kind,key)
            except CollectionRunCancelled:raise
            except ValueError:self.partial=True
        for member in items:
            self.heartbeat()
            provider=member['provider'];identifier=member['external_id']
            if provider=='imdb':continue
            try:
                if provider=='tmdb':
                    def load(value=identifier):
                        data=self.tmdb('/'+kind+'/'+value)
                        if data.get('id')!=int(value) or not (data.get('title') or data.get('name')):
                            raise UnresolvedFranchiseIdentity('collections.franchises_source_failed')
                        return data
                    rows.append(self.cached(['franchise-local-member-v1',kind,identifier,self.language],24*30,load))
                else:
                    if kind!='tv':raise UnresolvedFranchiseIdentity('collections.franchises_source_failed')
                    def find(value=identifier):
                        matches=self.tmdb('/find/'+value,external_source='tvdb_id').get('tv_results')
                        if not isinstance(matches,list) or len(matches)!=1:
                            raise UnresolvedFranchiseIdentity('collections.franchises_source_failed')
                        return matches[0]
                    rows.append({**self.cached(['franchise-local-tvdb-v1',identifier,self.language],24*30,find),'tvdb_id':identifier})
            except CollectionRunCancelled:raise
            except (RequestException,UnresolvedFranchiseIdentity):
                self.partial=True
        result=[];seen=set()
        for row in rows:
            identifier=row.get('id');title=row.get('title') or row.get('name')
            if type(identifier) is not int or identifier<=0 or not title:
                raise ValueError('collections.franchises_source_failed')
            if identifier in seen:continue
            seen.add(identifier)
            date=row.get('release_date') or row.get('first_air_date') or ''
            result.append({**row,'title':title,'year':str(date)[:4],'sources':['franchise_universe'],
                'source_kinds':{'franchise_universe':'vodum'},'ranks_by_source':{'franchise_universe':len(result)+1},'buzz_score':0})
        if self.partial and not result and items:
            raise ValueError('collections.franchises_source_failed')
        result.sort(key=lambda row:(row.get('release_date') or row.get('first_air_date') or '9999',row['id']))
        return definition['name'],None,result
