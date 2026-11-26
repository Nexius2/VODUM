"""Offline catalogue checks, bounded provider preparation and read-only migration preview."""
import copy
import hashlib
import json
import re
from pathlib import Path
from core.collection_lists import identity, read_cursor

DATA=Path(__file__).resolve().parents[1]/'data'


def content_digest(catalog):
    value={key:value for key,value in catalog.items() if key not in ('status','review')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def catalog_review(catalog, universes=None):
    """Report evidence gaps; never infer approval from the word 'ready'."""
    universes=universes if universes is not None else json.loads((DATA/'franchise_universes.json').read_text(encoding='utf-8'))['universes']
    issues=[]; summaries=[]; seen=set(); mappings=set()
    if not isinstance(catalog,dict) or type(catalog.get('schema_version')) is not int or catalog.get('schema_version')!=1 or type(catalog.get('catalog_version')) is not int or catalog['catalog_version']<1 or not isinstance(catalog.get('lists'),list):
        return {'eligible':False,'issues':[{'code':'invalid_catalog'}],'lists':[]}
    expected={'vodum.franchise.'+key:'universe_v2_'+key for key in universes}
    for row in catalog['lists']:
        if not isinstance(row,dict):
            issues.append({'code':'invalid_list'});continue
        key=row.get('id')
        if not isinstance(key,str) or key in seen:
            issues.append({'code':'duplicate_or_invalid_list'});continue
        seen.add(key)
        legacy=row.get('legacy_key')
        if not isinstance(legacy,str) or key not in expected or legacy!=expected[key] or legacy in mappings:
            issues.append({'list_id':key,'code':'legacy_mapping_invalid'})
        if isinstance(legacy,str):mappings.add(legacy)
        if not isinstance(row.get('name'),str) or not row['name'].strip():
            issues.append({'list_id':key,'code':'missing_name'})
        members=row.get('members'); identities=set(); aliases={}; missing=0
        if not isinstance(members,list) or not members:
            issues.append({'list_id':key,'code':'empty_or_invalid_members'});continue
        for index,member in enumerate(members):
            try:
                media=identity(member)
                if media in identities:raise ValueError('Duplicate identity')
                identities.add(media)
            except (ValueError,TypeError,AttributeError):
                issues.append({'list_id':key,'index':index,'code':'invalid_or_duplicate_identity'});continue
            if media[0]!='tmdb':
                issues.append({'list_id':key,'index':index,'code':'noncanonical_identity'})
            if (not isinstance(member.get('title'),str) or not member['title'].strip()
                    or not re.fullmatch(r'[1-2][0-9]{3}',str(member.get('year','')))):
                missing+=1
            values=member.get('aliases',[])
            if not isinstance(values,list):
                issues.append({'list_id':key,'index':index,'code':'invalid_alias'});continue
            for alias in values:
                try:
                    alias_id=identity(alias)
                    if alias_id[1]!=media[1] or (alias_id[0]=='tmdb' and alias_id!=media) or alias_id in aliases and aliases[alias_id]!=media:
                        raise ValueError('Conflicting alias')
                    aliases[alias_id]=media
                except (ValueError,TypeError,AttributeError):
                    issues.append({'list_id':key,'index':index,'code':'invalid_alias'})
        if missing:issues.append({'list_id':key,'count':missing,'code':'missing_metadata'})
        summaries.append({'id':key,'members':len(members),'missing_metadata':missing})
    for key in sorted(set(expected)-seen):issues.append({'list_id':key,'code':'missing_legacy_list'})
    review=catalog.get('review',{})
    if not isinstance(review,dict) or review.get('content_digest')!=content_digest(catalog):
        issues.append({'code':'review_missing_or_stale'})
    for check in ('source_coverage_verified',):
        if not isinstance(review,dict) or review.get(check) is not True:issues.append({'code':check})
    if catalog.get('status')!='ready':issues.append({'code':'catalog_not_ready'})
    return {'eligible':not issues,'content_digest':content_digest(catalog),'issues':issues,'lists':summaries}


def require_release_catalog(catalog):
    report=catalog_review(catalog)
    if not report['eligible']:
        raise ValueError('Official franchise catalogue has unresolved release checks')
    return catalog


def prepare_catalog(catalog, resolver, *, max_requests=100, heartbeat=lambda:None):
    """Return a draft; a caller supplies an existing TMDb resolver and cache.

    Network work has a per-invocation budget. Provider failures never turn a
    partially resolved list into an approved catalogue or trigger installation.
    """
    if type(max_requests) is not int or max_requests<1:
        raise ValueError('Invalid request budget')
    result=copy.deepcopy(catalog);result['status']='draft';result.pop('review',None)
    problems=[]; requests_used=0; cache={}
    def get(path,**params):
        nonlocal requests_used
        cache_key=json.dumps([path,params],sort_keys=True)
        if cache_key not in cache:
            if requests_used>=max_requests:raise ValueError('request_budget')
            requests_used+=1;heartbeat()
            cache[cache_key]=resolver.tmdb(path,**params)
        return cache[cache_key]
    for row in result['lists']:
        resolved={}; unresolved=[]
        for member in row['members']:
            heartbeat()
            try:
                provider,kind,identifier=identity(member)
                if provider=='tmdb':media_id=int(identifier)
                else:
                    if provider=='tvdb' and kind!='tv':raise ValueError('unsupported_identity')
                    found=get('/find/'+identifier,external_source=provider+'_id').get('movie_results' if kind=='movie' else 'tv_results')
                    if not isinstance(found,list) or len(found)!=1:raise ValueError('ambiguous_identity')
                    media_id=found[0].get('id')
                if type(media_id) is not int or media_id<=0:raise ValueError('invalid_identity')
                if provider=='tmdb' and isinstance(member.get('title'),str) and member['title'].strip() and re.fullmatch(r'[1-2][0-9]{3}',str(member.get('year',''))):
                    detail={'id':media_id,'title':member['title'],'release_date':str(member['year'])}
                else:
                    detail=get('/'+kind+'/'+str(media_id))
                title=detail.get('title') or detail.get('name')
                year=str(detail.get('release_date') or detail.get('first_air_date') or '')[:4]
                if detail.get('id')!=media_id or not isinstance(title,str) or not title.strip() or not re.fullmatch(r'[1-2][0-9]{3}',year):
                    raise ValueError('missing_metadata')
                key=(kind,str(media_id))
                item=resolved.setdefault(key,{'provider':'tmdb','media_type':kind,'external_id':str(media_id),
                    'title':title,'year':year,'aliases':[]})
                for alias in [*member.get('aliases',[]),{'provider':provider,'media_type':kind,'external_id':identifier}]:
                    identity(alias)
                    if alias['provider']!='tmdb' and alias not in item['aliases']:item['aliases'].append(alias)
            except Exception as exc:
                from core.collections_repository import CollectionRunCancelled
                if isinstance(exc,CollectionRunCancelled):raise
                # Keep unresolved source identities so a later preparation can
                # retry without losing membership. Never persist provider text.
                unresolved.append(member)
                code=str(exc) if isinstance(exc,ValueError) and str(exc) in ('request_budget','unsupported_identity','ambiguous_identity','invalid_identity','missing_metadata') else 'provider_failure'
                problems.append({'list_id':row['id'],'identity':':'.join(str(member.get(k,'')) for k in ('provider','media_type','external_id')) if isinstance(member,dict) else 'invalid','code':code})
        row['members']=[*resolved.values(),*unresolved]
    return result,{'requests':requests_used,'unresolved':problems,'status':'draft'}


def migration_preview(db,catalog):
    """Return a plan only. No import, association, job or object mutation."""
    report=catalog_review(catalog)
    mapping={row['id']:row.get('legacy_key') for row in catalog.get('lists',[]) if isinstance(row,dict) and isinstance(row.get('id'),str) and isinstance(row.get('legacy_key'),str)}
    groups=[]
    with read_cursor(db) as cur:
        instances=cur.execute("SELECT * FROM collection_instances WHERE model='franchises' ORDER BY COALESCE(group_id,id),id").fetchall()
        for instance in instances:
            instance=dict(instance); group_id=instance.get('group_id') or instance['id']
            objects=[dict(row) for row in cur.execute('SELECT id,person_key,remote_id,title FROM collection_objects WHERE instance_id=? ORDER BY id',(instance['id'],)).fetchall()]
            entries=[];conflicts=[]
            for list_id,legacy in mapping.items():
                old=[obj for obj in objects if obj['person_key']=='franchise:movie:'+legacy]
                new=[obj for obj in objects if obj['person_key']=='list:movie:'+list_id]
                if new:conflicts.append(list_id)
                entries.append({'list_id':list_id,'legacy_object_key':'franchise:movie:'+legacy,
                                'preserve_object_ids':[obj['id'] for obj in old]})
            groups.append({'group_id':group_id,'instance_id':instance['id'],'library_id':instance['library_id'],
                'enabled':bool(instance['enabled']),'retired':bool(instance['retired']),
                'busy':bool(instance['lease_id'] or instance['requested'] not in (None,'sync')),'lists':entries,'conflicts':conflicts})
    return {'eligible':report['eligible'] and not any(row['busy'] or row['conflicts'] for row in groups),
            'catalog_review':report,'instances':groups,'writes':0}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=DATA/'collection_lists.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=catalog_review(json.loads(args.catalog.read_text(encoding='utf-8')))
    payload=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.write_text(payload,encoding='utf-8')
    else:
        print(payload,end='')
    return 0 if report['eligible'] else 2


if __name__=='__main__':
    raise SystemExit(main())
