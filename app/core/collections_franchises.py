"""Publish curated film franchises and retire former owned sagas."""
import json
import os
import re
import time
from requests import RequestException

from core.collection_inventory import CachedCollectionMedia
from core.collections_media import media_adapter, CollectionOwnershipError
from core.collections_repository import CollectionRunCancelled
from core.collections_streaming import run_streaming_country
from core.collections_streaming_source import StreamingSource
from core.error_reporting import log_handled_failure
from core.collections_universes import UniverseLists, UnresolvedFranchiseIdentity
from core.collections_universes_catalog import UNIVERSES
from secret_store import decrypt_secret


class FranchiseSource(UniverseLists, StreamingSource):
    discovery_budget_seconds = 120

    def local_ids(self, inventory, kind):
        ids=set(); failures=0; last_failure=None
        deadline=time.monotonic()+self.discovery_budget_seconds
        for row in inventory:
            self.heartbeat()
            # Direct identities cost no network calls, including after the
            # lookup budget has elapsed. Never discard a known local TMDb ID.
            direct=str(row.get('tmdb') or '')
            if direct.isdigit() and int(direct)>0:
                ids.add(int(direct));continue
            if time.monotonic()>=deadline:
                self.partial=True
                continue
            try:
                resolved=None
                providers=('tvdb','imdb') if kind=='tv' else ('imdb','tvdb')
                for provider in providers:
                    value=str(row.get(provider) or '')
                    if not re.fullmatch(r'tt[0-9]+' if provider=='imdb' else r'[1-9][0-9]*',value):
                        continue
                    try:
                        def resolve_local(p=provider,v=value):
                            data=self.tmdb('/find/'+v,external_source=p+'_id')
                            matches=data.get('movie_results' if kind=='movie' else 'tv_results')
                            if not isinstance(matches,list) or not matches:
                                raise UnresolvedFranchiseIdentity('collections.streaming_identity_failed')
                            return data
                        found=self.cached(['franchise-local-find-v2',kind,provider,value],24*30,resolve_local)
                    except (RequestException, UnresolvedFranchiseIdentity):
                        # One provider's failed lookup need not hide an exact
                        # identity available through the other provider.
                        continue
                    matches=found.get('movie_results' if kind=='movie' else 'tv_results')
                    if not isinstance(matches,list) or len(matches)>1:
                        raise ValueError('collections.streaming_identity_failed')
                    if matches:
                        identifier=matches[0].get('id')
                        if type(identifier) is not int or identifier<=0:
                            raise ValueError('collections.streaming_identity_failed')
                        resolved=identifier
                        break
                if resolved is None:
                    raise ValueError('collections.streaming_identity_failed')
                ids.add(resolved)
                # Share this verified resolution with every child collection;
                # otherwise each saga resolves its candidates all over again.
                row['tmdb']=str(resolved)
            except CollectionRunCancelled:raise
            except Exception as exc:
                self.partial=True;failures+=1
                last_failure={'provider':'tmdb','country':'franchises','media_type':kind,
                              'stage':'identity','error_type':type(exc).__name__,
                              'reason':'franchise_local_identity_unresolved'}
        if failures:
            self.diagnostics.append({'id':'franchise_identity','name':'TMDb','state':'warning',
                'count':failures,'failure':last_failure})
        return ids

    def groups(self, inventory, kind):
        self.partial = False
        self.diagnostics = []
        self.franchise_identity_network_blocked=False
        groups = self.universe_groups(kind)
        self.resolved_local_ids = self.local_ids(inventory, kind) if groups else set()
        self.local_franchise_media={str(row['imdb']):{'id':int(row['tmdb']),'title':row['title'],
            'release_date':str(row.get('release_date') or '')[:10]}
            for row in inventory if row.get('imdb') and str(row.get('tmdb') or '').isdigit()
            and int(row['tmdb'])>0 and row.get('title')}
        return groups

    def members(self, group, kind):
        return self.universe_members(group['universe'], kind)


def run_franchises(db,instance,*,kind='sync',heartbeat=lambda:None,
                   source_factory=FranchiseSource,adapter_factory=media_adapter):
    config=json.loads(instance['config_json']);preview=kind=='preview'
    library=dict(db.query_one('SELECT * FROM libraries WHERE id=?',(instance['library_id'],)))
    server=dict(db.query_one('SELECT * FROM servers WHERE id=?',(library['server_id'],)))
    media_type='movie' if library['type'] in ('movie','movies','films','film') else 'tv'
    adapter=source=None;inventory=None;children={}
    result={'people':[],'present':0,'missing':0,'arr_requests':0,'arr_planned':0,'warnings':[],
            'errors':[],'arr_details':[],'preview':preview,'diagnostics':{'providers':[]},'stage':'discovery'}
    def get_adapter():
        nonlocal adapter
        if adapter is None:
            adapter=CachedCollectionMedia(db,server,library) if adapter_factory is media_adapter else adapter_factory(server,library)
            adapter.heartbeat=heartbeat
        return adapter
    class SharedAdapter:
        def inventory(self):return inventory
        def close(self):pass
        def __getattr__(self,key):return getattr(get_adapter(),key)
    class PreparedSource:
        # Local identities were already resolved once by FranchiseSource.
        # Re-querying every absent candidate because a few unrelated local
        # titles lack identities creates thousands of avoidable HTTP requests.
        match_resolved_inventory_only=True
        def __init__(self,rows,poster,provider='TMDb'):
            self.rows=rows;self.collection_profile_path=poster
            self.partial=source.partial
            self.local_identity_uncertain=any(not row.get('tmdb') for row in inventory)
            self.diagnostics=[{'id':'franchise_members','name':{'imdb':'IMDb','imdb_lists':'IMDb','tmdb':'TMDb','tmdb_collection':'TMDb'}.get(provider,provider),'state':'success','count':len(rows),'source_kind':'franchise_universe' if provider!='TMDb' else 'tmdb_franchise'}]
        def discover(self,*args):return self.rows
        def close(self):pass
        def media_external_ids(self,*args):return source.media_external_ids(*args)
    def report(key,child):
        children[key]=child
        for field in ('present','missing','arr_requests','arr_planned'):
            result[field]=sum(row.get(field,0) for row in children.values())
        for field in ('people','arr_details'):
            result[field]=[item for row in children.values() for item in row.get(field,[])]
        for field in ('warnings','errors'):
            result[field]=list(dict.fromkeys(result[field]+[item for row in children.values() for item in row.get(field,[])]))
        result['diagnostics']['providers']=(list(source.diagnostics) if source else [])+[
            {**provider,'name':next((person['name'] for person in row.get('people',[])),name)+' · '+provider['name']}
            for name,row in children.items() for provider in row.get('diagnostics',{}).get('providers',[])]
        result['stage']=child.get('stage','selection')
        reporter=getattr(heartbeat,'report',None)
        if callable(reporter):reporter(result)
    def remove(obj):
        heartbeat()
        if obj['remote_id']:get_adapter().delete(obj)
        db.execute("UPDATE collection_objects SET state='deleted',remote_id=NULL WHERE id=?",(obj['id'],))
        obj.update(state='deleted',remote_id=None)
    try:
        objects=[dict(row) for row in db.query('SELECT * FROM collection_objects WHERE instance_id=?',(instance['id'],))]
        if kind in ('cleanup','delete'):
            for obj in objects:
                if obj['state']!='deleted':remove(obj)
            result.update(stage='complete',outcome='empty');return result
        if kind=='expire':return result
        inventory=get_adapter().inventory()
        shared=db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key=decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        source=source_factory(key,config['language']);source.db=db;source.heartbeat=heartbeat
        groups=source.groups(inventory,media_type)
        local_ids=source.resolved_local_ids
        result['diagnostics']['providers']=source.diagnostics
        result['diagnostics']['partial']=source.partial
        if source.partial:result['warnings'].append('collections.streaming_partial')
        # Keep uncertainty scoped to the affected franchise. A failed source
        # prevents retirement of old sagas, but does not block verified groups.
        identity_partial = source.partial
        prepared = {}
        group_partials = {}
        for group in groups:
            try:
                source.partial = identity_partial
                prepared[group['key']] = source.members(group,media_type)
                group_partials[group['key']] = source.partial
            except CollectionRunCancelled:
                raise
            except Exception as exc:
                result['errors'].append('collections.franchises_source_failed')
                result['diagnostics']['providers'].append({
                    'id':group['key'],'name':group['title'],'state':'error',
                    'failure':source.failure(exc,UNIVERSES[group['universe']]['provider'],
                                             'franchises',media_type,'members')})
        any_partial = identity_partial or any(group_partials.values())
        source.partial = any_partial
        result['diagnostics']['partial'] = any_partial
        if any_partial:
            result['warnings'].append('collections.streaming_partial')
        can_retire = not result['errors'] and not any_partial
        new_keys = {'franchise:'+media_type+':'+group['key'] for group in groups}
        if not preview and can_retire:
            for obj in objects:
                if obj['person_key'] not in new_keys and obj['state']!='deleted':
                    remove(obj)
        active=set(); universe_titles={group['title'] for group in groups if group.get('universe')}
        for group in groups:
            heartbeat();object_key='franchise:'+media_type+':'+group['key'];active.add(object_key)
            if group['key'] not in prepared:
                continue
            source.partial = group_partials[group['key']]
            try:
                title,poster,rows=prepared[group['key']]
                if not group.get('universe') and title in universe_titles:
                    continue
                matched_titles=set()
                for credit in rows:
                    if credit['id'] in local_ids:
                        matched_titles.add(credit['id'])
                        continue
                    if any(not local.get('tmdb') and any(
                        credit.get(provider+'_id') and str(credit[provider+'_id'])==str(local.get(provider) or '')
                        for provider in ('imdb','tvdb')) for local in inventory):
                        matched_titles.add(credit['id'])
                local_count=len(matched_titles)
                # Match upstream's minimum: two distinct titles, not two editions.
                if local_count<2:
                    old=next((obj for obj in objects if obj['person_key']==object_key),None)
                    if old and not preview and not source.partial:remove(old)
                    continue
                # If a different source failed, obsolete objects were kept.
                # Reuse an exact-title object belonging to this configuration
                # so verified groups do not collide with their own old title.
                if not preview and not can_retire and not any(obj['person_key']==object_key for obj in objects):
                    old=next((obj for obj in objects if obj['title']==title and obj['state']!='deleted'
                              and obj['person_key'].startswith('franchise:'+media_type+':')),None)
                    if old:
                        db.execute('UPDATE collection_objects SET person_key=? WHERE id=?',(object_key,old['id']))
                        old['person_key']=object_key
                def child_heartbeat():heartbeat()
                child_heartbeat.report=lambda child,k=object_key:report(k,child)
                provider=next((row['source_kinds']['franchise_universe'] for row in rows if 'franchise_universe' in row.get('source_kinds',{})),'TMDb')
                factory=lambda *args,r=rows,p=poster,s=provider:PreparedSource(r,p,s)
                child_config={**config,'country':'FR','limit':0,'native_release_order':True,'publication_budget_seconds':30}
                child=run_streaming_country(db,{**instance,'config_json':json.dumps(child_config)},kind=kind,
                    heartbeat=child_heartbeat,source_factory=factory,adapter_factory=lambda *args:SharedAdapter(),
                    object_key_override=object_key,title_override=title,
                    poster_key_override='universe_'+group['universe'] if group.get('universe') else 'franchises')
                report(object_key,child)
            except CollectionRunCancelled:raise
            except CollectionOwnershipError as exc:
                if str(exc)!='collections.title_collision':raise
                # An external collection with this title blocks only
                # this saga. Do not adopt it and do not stop the other sagas.
                child=getattr(exc,'result',{})
                child.setdefault('warnings',[]).append('collections.title_collision')
                child.setdefault('diagnostics',{}).setdefault('providers',[]).append({
                    'id':object_key,'name':title,'state':'error','source_kind':'collection_publication',
                    'failure':{'stage':'title_collision'}})
                report(object_key,child)
            except Exception as exc:
                log_handled_failure('collections.franchises.collection',level='error')
                result['errors'].append('collections.franchises_source_failed')
                provider=UNIVERSES[group['universe']]['provider'] if group.get('universe') else 'tmdb'
                report(object_key,{'errors':['collections.franchises_source_failed'],'diagnostics':{'providers':[{
                    'id':object_key,'name':group.get('title') or object_key,'state':'error',
                    'source_kind':'franchise_universe' if group.get('universe') else 'tmdb_franchise',
                    'failure':source.failure(exc,provider,'franchises',media_type,'members')}]}})
        if not preview and can_retire:
            for obj in objects:
                if obj['person_key'] not in active and obj['state']!='deleted':remove(obj)
        result.update(stage='complete',outcome='preview' if preview else 'failed' if result['errors'] else 'published' if any(row.get('published') for row in result['people']) else 'empty')
        reporter=getattr(heartbeat,'report',None)
        if callable(reporter):reporter(result)
        return result
    except (CollectionRunCancelled,CollectionOwnershipError) as exc:
        exc.result=result;raise
    finally:
        if source is not None:source.close()
        if adapter is not None:adapter.close()
