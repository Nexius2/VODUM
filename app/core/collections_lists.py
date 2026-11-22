"""Publish explicitly associated lists without retiring remote collections."""
from core.collections_repository import CollectionRunCancelled
from core.collections_media import CollectionOwnershipError
from core.collections_streaming import run_streaming_country
from core.error_reporting import log_handled_failure


class ListSource:
    match_resolved_inventory_only = True
    collection_profile_path = None

    def __init__(self, rows, partial, inventory, resolver):
        self.rows = rows
        self.partial = partial
        self.local_identity_uncertain = any(not row.get('tmdb') for row in inventory)
        self.diagnostics = [{'id': 'internal_list', 'name': 'VODUM Lists',
                             'state': 'warning' if partial else 'success', 'count': len(rows)}]
        self.resolver = resolver

    def discover(self, *args):
        return self.rows

    def close(self):
        pass

    def media_external_ids(self, *args):
        return self.resolver.media_external_ids(*args)


def list_candidates(detail, kind, inventory, resolver, heartbeat):
    """Resolve typed identities; never match by name or accept ambiguous aliases."""
    rows = {}
    partial = False
    for member in detail['effective_members']:
        if member['media_type'] != kind:
            continue
        heartbeat()
        provider, identifier = member['provider'], str(member['external_id'])
        try:
            if provider == 'tmdb':
                data = {'id': int(identifier)}
            else:
                local = [row for row in inventory if str(row.get(provider) or '') == identifier and row.get('tmdb')]
                ids = {int(row['tmdb']) for row in local if str(row['tmdb']).isdigit() and int(row['tmdb']) > 0}
                if len(ids) > 1:
                    raise ValueError('Ambiguous identity')
                if ids:
                    data = {'id': next(iter(ids))}
                else:
                    if provider == 'tvdb' and kind != 'tv':
                        raise ValueError('TVDB movie identities are unsupported')
                    def find():
                        response = resolver.tmdb('/find/'+identifier, external_source=provider+'_id')
                        matches = response.get('movie_results' if kind == 'movie' else 'tv_results')
                        if not isinstance(matches, list) or len(matches) != 1:
                            raise ValueError('Unresolved identity')
                        value = matches[0]
                        if type(value.get('id')) is not int or value['id'] <= 0:
                            raise ValueError('Invalid identity')
                        return value
                    data = resolver.cached(['internal-list-find-v1', kind, provider, identifier], 24*30, find)
            media_id = data['id']
            local = next((row for row in inventory if str(row.get('tmdb') or '') == str(media_id)), {})
            item = rows.setdefault(media_id, {**data, 'id': media_id,
                'title': member.get('title') or local.get('title') or data.get('title') or data.get('name') or str(media_id),
                'year': member.get('year') or local.get('year') or '',
                'release_date': data.get('release_date') or local.get('release_date') or str(member.get('year') or ''),
                'sources': ['internal_list'], 'source_kinds': {'internal_list': 'vodum_list'},
                'ranks_by_source': {'internal_list': len(rows)+1}, 'buzz_score': 0})
            for alias in member.get('aliases',[]):
                if alias.get('media_type')==kind and alias.get('provider') in ('imdb','tvdb'):
                    item[alias['provider']+'_id']=str(alias['external_id'])
            if provider in ('imdb', 'tvdb'):
                item[provider+'_id'] = identifier
        except CollectionRunCancelled:
            raise
        except Exception:
            partial = True
            log_handled_failure('collections.lists.identity')
    return list(rows.values()), partial


def publish_bound_lists(db, instance, lists, *, inventory, resolver, adapter_factory, heartbeat, report):
    import json
    config = json.loads(instance['config_json'])
    library = db.query_one('SELECT type FROM libraries WHERE id=?', (instance['library_id'],))
    media_type = 'movie' if library['type'] in ('movie', 'movies', 'film', 'films') else 'tv'
    for detail in lists:
        heartbeat()
        if not detail['enabled'] or not detail['available']:
            continue
        legacy=detail.get('legacy_key')
        object_key = 'franchise:'+media_type+':'+legacy if legacy else 'list:'+media_type+':'+detail['id']
        if config['mode'] == 'arr' and not legacy:
            report(object_key, {'warnings': ['collections.lists_arr_unavailable']})
            continue
        rows, partial = list_candidates(detail, media_type, inventory, resolver, heartbeat)
        if not rows:
            report(object_key, {'warnings': ['collections.lists_preserved'],
                               'diagnostics': {'partial': partial}})
            continue
        # No match is never permission to remove an old list publication.
        local_ids = {str(row.get('tmdb')) for row in inventory if row.get('tmdb')}
        matched_ids = {row['id'] for row in rows if str(row['id']) in local_ids or any(
            not local.get('tmdb') and any(row.get(provider+'_id') and str(row[provider+'_id']) == str(local.get(provider) or '')
                                        for provider in ('imdb', 'tvdb')) for local in inventory)}
        has_match = len(matched_ids) >= (2 if legacy else 1)
        if not has_match:
            report(object_key, {'missing': len(rows), 'warnings': ['collections.lists_preserved']})
            continue
        if legacy:
            present={row['id'] for row in rows if str(row['id']) in local_ids or any(
                not local.get('tmdb') and any(row.get(provider+'_id') and str(row[provider+'_id'])==str(local.get(provider) or '') for provider in ('imdb','tvdb')) for local in inventory)}
            if len(present)<2:
                report(object_key,{'warnings':['collections.lists_preserved']})
                continue
        source = ListSource(rows, partial, inventory, resolver)
        child_config = {**config, 'arr_enabled': config['arr_enabled'] if legacy else False, 'country': 'FR', 'limit': 0,
                        'native_release_order': True, 'publication_budget_seconds': 30, '_preserve_empty': True}
        def child_heartbeat():
            heartbeat()
        child_heartbeat.report = lambda child, key=object_key: report(key, child)
        try:
            child = run_streaming_country(db, {**instance, 'config_json': json.dumps(child_config)},
                kind='preview' if config.get('_list_preview') else 'sync', heartbeat=child_heartbeat, uses_tmdb=False,
                source_factory=lambda *args: source, adapter_factory=adapter_factory,
                object_key_override=object_key, title_override=detail['name'], poster_key_override='universe_'+legacy.removeprefix('universe_v2_') if legacy else 'franchises')
            report(object_key, child)
        except CollectionRunCancelled:
            raise
        except CollectionOwnershipError as exc:
            if str(exc) != 'collections.title_collision':
                raise
            report(object_key, {'warnings': ['collections.title_collision']})
        except Exception:
            log_handled_failure('collections.lists.publication', level='error')
            report(object_key, {'errors': ['collections.franchises_source_failed']})
