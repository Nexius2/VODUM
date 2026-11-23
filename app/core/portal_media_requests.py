"""User-scoped media search and checked, deterministic ARR submissions."""
import json
import time
import requests as http_requests
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from uuid import uuid4
from urllib.parse import quote, urlsplit
from core.http_security import server_http_session
from logging_utils import get_logger
from core.library_request_routing import compatible_arr_type, route_matches_media
from core.portal_media_requests_seerr import (seerr_can_request_4k, seerr_details, seerr_error_result,
    seerr_find_user, seerr_is_4k, seerr_media_state, seerr_metadata, seerr_request_payload,
    seerr_request_result, seerr_request_state, seerr_search, seerr_seasons, seerr_user_lookup_keys)
from core.portal_media_requests_tvdb import (covers_seasons, default_server_missing, details_tvdb_id,
                                              find_existing_request,
                                              resolve_tvdb, sonarr_candidates, tvdb_options)
from core.portal_provider_identity_state import row_media_identity_is_usable
from core.plex_guids import plex_external_guid
from core.portal_request_options import request_options
from db_manager import isolated_read_operation

CLAIM_SCHEMA = """CREATE TABLE IF NOT EXISTS portal_media_request_claims (
 kind TEXT NOT NULL, external_id INTEGER NOT NULL, owner TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(kind,external_id)
)"""

_request_deadline = ContextVar('media_request_deadline', default=None)
PROVIDER_ID_FIELDS = (('tmdb', 'tmdbId'), ('tvdb', 'tvdbId'), ('imdb', 'imdbId'))

class MediaRequestError(ValueError):
    pass


def parallel_reads(jobs):
    """Run bounded HTTP reads; keep SQLite and writes on the caller thread.

    Each worker inherits the submission deadline. Results retain input order
    so server priority and error handling do not depend on network timing.
    """
    if not jobs: return []
    def run(job):
        try: return job()
        except MediaRequestError as exc: return exc
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        futures = [pool.submit(copy_context().run, run, job) for job in jobs]
        return [future.result() for future in futures]


def api(server, path, *, params=None, payload=None):
    deadline = _request_deadline.get()
    timeout = min(12, deadline - time.monotonic()) if deadline is not None else 12
    if timeout <= 0: raise MediaRequestError('portal_requests_unavailable')
    http = server_http_session(server)
    log_path = path.split('?', 1)[0]
    kind = str(server['type']).lower()
    headers = {'Accept':'application/json'}
    headers['X-Plex-Token' if kind == 'plex' else ('X-Emby-Token' if kind == 'jellyfin' else 'X-Api-Key')] = server.get('token') or ''
    try:
        bases = list(dict.fromkeys(str(server.get(key) or '').strip().rstrip('/')
                                  for key in ('url','local_url','public_url')
                                  if str(server.get(key) or '').strip()))
        if not bases:
            raise MediaRequestError('portal_requests_unavailable')
        # Only reads may fail over. A lost POST response may hide a successful
        # remote addition, so never replay it on another address.
        if payload is not None:
            bases = bases[:1]
        read_deadline = deadline if deadline is not None else time.monotonic() + 24
        for index, base in enumerate(bases):
            remaining = read_deadline - time.monotonic()
            if remaining <= 0:
                raise MediaRequestError('portal_requests_unavailable')
            try:
                response = http.request('POST' if payload is not None else 'GET', base + path,
                                        params=params, json=payload, headers=headers,
                                        timeout=min(timeout,remaining), allow_redirects=False)
            except http_requests.exceptions.SSLError:
                raise
            except (http_requests.exceptions.ConnectionError,http_requests.exceptions.Timeout):
                if index == len(bases)-1:
                    raise
                continue
            if response.status_code in (502,503,504) and index < len(bases)-1:
                response.close()
                continue
            break
        if response.status_code not in (200,201):
            fields = []
            try:
                validation = response.json()
                allowed = {'QualityProfileId','RootFolderPath','Path','Title','TvdbId','TmdbId','MinimumAvailability','Seasons','SeriesType','LanguageProfileId','Monitored','AddOptions'}
                fields = sorted({row.get('propertyName') for row in validation if isinstance(row,dict) and row.get('propertyName') in allowed}) if isinstance(validation,list) else []
            except (ValueError,TypeError):
                pass
            get_logger('portal_media_requests').warning(
                'Media request API failure server_id=%s type=%s method=%s endpoint=%s http=%s validation_fields=%s',
                server.get('id'),kind,'POST' if payload is not None else 'GET',log_path,response.status_code,fields)
            error = MediaRequestError('portal_requests_add_failed' if payload is not None else 'portal_requests_unavailable')
            error.http_status, error.validation_fields, error.endpoint = response.status_code,fields,log_path
            raise error
        data = response.json()
        if not isinstance(data,(dict,list)): raise MediaRequestError('portal_requests_unavailable')
        return data
    except MediaRequestError:
        raise
    except Exception as exc:
        get_logger('portal_media_requests').warning(
            'Media request API connection failure server_id=%s type=%s method=%s endpoint=%s error_type=%s',
            server.get('id'),kind,'POST' if payload is not None else 'GET',log_path,type(exc).__name__)
        error = MediaRequestError('portal_requests_add_uncertain' if payload is not None else 'portal_requests_unavailable')
        error.endpoint, error.connection_error = log_path,type(exc).__name__
        raise error from None
    finally:
        http.close()


def accessible_libraries(db, user_id):
    rows = db.query("""SELECT l.*, s.name AS server_name, mu.details_json,mu.raw_json,
        mu.accepted_at, COALESCE(rs.requests_enabled,1) AS requests_enabled,
        COALESCE(rs.default_for_requests,0) AS preferred,
        COALESCE(rs.request_priority,100) AS request_priority
        FROM libraries l JOIN servers s ON s.id=l.server_id
        JOIN media_user_libraries mul ON mul.library_id=l.id
        JOIN media_users mu ON mu.id=mul.media_user_id AND mu.server_id=l.server_id
        LEFT JOIN library_request_settings rs ON rs.library_id=l.id
        WHERE mu.vodum_user_id=? AND LOWER(s.type) IN ('plex','jellyfin')
        ORDER BY preferred DESC, request_priority, l.id""", (user_id,)) or []
    result = {}
    for source in rows:
        row = dict(source)
        try: state = json.loads(row.get('raw_json') or '{}')
        except (TypeError,ValueError): state = {}
        if not isinstance(state,dict): state = {}
        try: details = json.loads(row.get('details_json') or '{}')
        except (TypeError,ValueError): details = {}
        if isinstance(details,dict): state.update(details)
        if not row_media_identity_is_usable(row) or state.get('is_pending'):
            continue
        if state.get('is_friend') is False and not row.get('accepted_at'):
            continue
        if compatible_arr_type(row['type']):
            result.setdefault(row['id'], row)
    return list(result.values())


def linked_arrs(db, library, backend=None):
    """Request services routed to a library, ordered by priority.

    ``backend`` restricts the result to ``'arr'`` (Sonarr/Radarr) or ``'seerr'``.
    Without explicit routes, the first ready ARR of the compatible kind applies.
    Seerr always requires an explicit library authorization.
    """
    if backend is None:
        backend = request_options(db)[0]
    if backend not in ('arr', 'seerr'):
        return []
    provider = compatible_arr_type(library['type'])
    configured = db.query('SELECT * FROM library_arr_routes WHERE library_id=? ORDER BY priority,arr_server_id', (library['id'],)) or []
    if configured:
        ids = [(r['arr_server_id'],r['priority']) for r in configured if r['enabled']]
    else:
        first = next((row for row in (db.query('SELECT * FROM servers WHERE LOWER(type)=? ORDER BY id', (provider,)) or [])
                      if has_saved_request_defaults(dict(row))), None) if backend == 'arr' else None
        # A Seerr library checkbox is an explicit authorization, never a fallback.
        ids = [(first['id'],1)] if first else []
    result = []
    for arr_id, priority in ids:
        server = db.query_one("SELECT * FROM servers WHERE id=? AND LOWER(type) IN (?,'seerr')", (arr_id,provider))
        if server and request_backend_ready(dict(server)) and (backend is None or request_backend(server) == backend):
            server = dict(server)
            row = db.query_one('SELECT conditions_json FROM library_arr_conditions WHERE library_id=? AND arr_server_id=?', (library['id'],arr_id))
            server['conditions'] = json.loads(row['conditions_json']) if row else {}
            server['priority'] = priority
            result.append(server)
    return result


def request_backend(server):
    return 'seerr' if str(server['type']).strip().lower() == 'seerr' else 'arr'


def request_backend_ready(server):
    """Seerr needs only its API key; an ARR also needs saved request defaults."""
    if request_backend(server) == 'seerr':
        return True
    return has_saved_request_defaults(server)


def media_requests_backend_ready(db, backend=None):
    """True when the portal can route at least one request somewhere."""
    rows = db.query("SELECT type, settings_json FROM servers WHERE LOWER(type) IN ('sonarr','radarr','seerr')") or []
    if backend is None:
        backend = request_options(db)[0]
    return any(request_backend_ready(dict(row)) and (backend == 'any' or request_backend(row) == backend) for row in rows)


def request_libraries(db, user_id):
    backend = request_options(db)[0]
    return [r for r in accessible_libraries(db,user_id) if r['requests_enabled'] and linked_arrs(db,r,backend)]


def poster_url(media):
    for image in media.get('images') or []:
        if str(image.get('coverType') or '').lower() != 'poster': continue
        for key in ('remoteUrl','url'):
            value = image.get(key) or ''
            try:
                parts = urlsplit(value)
                port = parts.port
            except ValueError: continue
            if parts.scheme == 'https' and parts.hostname in ('image.tmdb.org','artworks.thetvdb.com') and not parts.username and not parts.password and port in (None,443):
                return value
    return None


def search_media(db, user_id, kind, term):
    if kind not in ('all','movie','series') or not 2 <= len(term.strip()) <= 100:
        raise MediaRequestError('portal_requests_invalid')
    kinds = ('movie','series') if kind == 'all' else (kind,)
    libraries = request_libraries(db,user_id)
    jobs, identities = [], []
    backend = request_options(db)[0]
    seerr_servers, seerr_kinds = {}, {}
    for media_kind in kinds:
        provider = 'radarr' if media_kind == 'movie' else 'sonarr'
        routed = [library for library in libraries if compatible_arr_type(library['type']) == provider]
        if not routed:
            continue
        if backend == 'arr' and any(linked_arrs(db, library, 'arr') for library in routed):
            servers = [dict(row) for row in db.query(
                'SELECT * FROM servers WHERE LOWER(type)=? ORDER BY id', (provider,))]
            for server in servers:
                identities.append(('arr', media_kind))
                jobs.append(lambda server=server, media_kind=media_kind:
                    api(server, '/api/v3/' + media_kind + '/lookup', params={'term':term.strip()}))
        for library in routed if backend == 'seerr' else []:
            for server in linked_arrs(db, library, 'seerr'):
                seerr_servers.setdefault(server['id'], server)
                seerr_kinds.setdefault(server['id'], set()).add(media_kind)
    # One Seerr search covers movies and series; ask each linked instance once.
    # The member's Seerr user is read alongside, so the card can offer 4K only
    # when Seerr would accept it.
    identity_keys = _member_identity_keys(db, user_id) if seerr_servers else None
    for server in seerr_servers.values():
        identities.append(('seerr', server['id']))
        jobs.append(lambda server=server: seerr_search(api, server, term.strip(), seerr_kinds[server['id']]))
        if any(identity_keys.values()):
            identities.append(('seerr_user', server['id']))
            jobs.append(lambda server=server: seerr_find_user(api, server, identity_keys))
    if not jobs: raise MediaRequestError('portal_requests_no_libraries')
    results = {media_kind:{} for media_kind in kinds}
    success = False
    deadline_token = _request_deadline.set(time.monotonic() + 24)
    try:
        outcomes = list(zip(identities, parallel_reads(jobs)))
    finally:
        _request_deadline.reset(deadline_token)
    seerr_users = {server_id: user for (source, server_id), user in outcomes
                   if source == 'seerr_user' and isinstance(user, dict)}
    for (source, media_kind), rows in outcomes:
        if source == 'seerr_user': continue
        if not isinstance(rows,list): continue
        success = True
        if source == 'seerr':
            server = seerr_servers[media_kind]
            user = seerr_users.get(server['id'])
            for row in rows:
                row['default_4k'] = seerr_is_4k(server)
                row['can_4k'] = bool(user) and seerr_can_request_4k(user['permissions'], row['kind'])
                results[row['kind']].setdefault(('seerr', row['external_id']), row)
            continue
        id_key = 'tmdbId' if media_kind == 'movie' else 'tvdbId'
        for item in rows:
            external_id = item.get(id_key)
            if not isinstance(external_id,int) or external_id <= 0: continue
            results[media_kind].setdefault(('arr', external_id), {'source':'arr', 'external_id':external_id, 'kind':media_kind,
                'title':item.get('title') or '', 'year':item.get('year'), 'overview':item.get('overview') or '',
                'poster':poster_url(item)})
    if not success: raise MediaRequestError('portal_requests_unavailable')
    groups = [list(results[media_kind].values()) for media_kind in kinds]
    return [row for index in range(max(map(len, groups), default=0))
            for group in groups for row in group[index:index+1]][:50]


def canonical_media(arrs, kind, external_id):
    key = 'tmdbId' if kind == 'movie' else 'tvdbId'
    term = ('tmdb:' if kind == 'movie' else 'tvdb:') + str(external_id)
    for server in arrs:
        try: rows = api(server,'/api/v3/'+kind+'/lookup',params={'term':term})
        except MediaRequestError: continue
        for row in rows if isinstance(rows,list) else []:
            if row.get(key) == external_id: return row
    raise MediaRequestError('portal_requests_unavailable')


def _arr_contains_media(server, kind, external_id):
    key = 'tmdbId' if kind == 'movie' else 'tvdbId'
    path = '/api/v3/' + kind
    try:
        rows = api(server, path, params={key: external_id})
    except MediaRequestError as exc:
        # Older servers may reject the query parameter. An HTTP or transport
        # failure unrelated to query validation still blocks the submission.
        if getattr(exc, 'http_status', None) not in (400, 422):
            raise
        rows = api(server, path)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise MediaRequestError('portal_requests_arr_unavailable')
    # Also works on servers which ignore the parameter and return all rows.
    return any(row.get(key) == external_id for row in rows)


def _provider_ids(media):
    return {provider: str(media[key]) for provider, key in PROVIDER_ID_FIELDS if media.get(key)}


def _has_plex_identity(item, expected):
    guids = item.get('Guid') or []
    if plex_external_guid(str(item.get('guid') or '')) in expected:
        return True
    return isinstance(guids, list) and any(
        isinstance(guid, dict) and plex_external_guid(str(guid.get('id') or '')) in expected
        for guid in guids
    )


def _has_jellyfin_identity(item, expected):
    providers = item.get('ProviderIds')
    if not isinstance(providers, dict):
        return False
    ids = {key.casefold(): str(value) for key, value in providers.items()}
    return any(ids.get(provider) == value for provider, value in expected.items())


@isolated_read_operation
def _inventory_hints(db, media):
    """Get at most one candidate per library without trusting inventory absence."""
    if not db.query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collection_inventory_media'"):
        return {}
    ids = _provider_ids(media)
    if not ids:
        return {}
    rows = db.query("""
        SELECT library_id, MIN(media_id) AS media_id
        FROM collection_inventory_media
        WHERE CASE WHEN json_valid(data_json) THEN
              CAST(json_extract(data_json, '$.tmdb') AS TEXT) = ?
           OR CAST(json_extract(data_json, '$.tvdb') AS TEXT) = ?
           OR CAST(json_extract(data_json, '$.imdb') AS TEXT) = ?
        END
        GROUP BY library_id
    """, tuple(ids.get(provider) for provider, _ in PROVIDER_ID_FIELDS))
    return {row['library_id']: row['media_id'] for row in rows}


def _confirm_inventory_hint(server, library, media, kind, item_id):
    ids = _provider_ids(media)
    if str(server['type']).lower() == 'plex':
        data = api(server, '/library/metadata/' + quote(str(item_id), safe=''), params={'includeGuids': 1})
        container = data.get('MediaContainer', {}) if isinstance(data, dict) else {}
        rows = container.get('Metadata') if isinstance(container, dict) else None
        if not isinstance(rows, list):
            return False
        return any(
            isinstance(item, dict)
            and str(item.get('ratingKey')) == str(item_id)
            and str(item.get('librarySectionID', container.get('librarySectionID'))) == str(library['section_id'])
            and item.get('type') == ('movie' if kind == 'movie' else 'show')
            and _has_plex_identity(item, ids.items())
            for item in rows
        )
    data = api(server, '/Items', params={
        'Ids': item_id, 'ParentId': library['section_id'], 'Recursive': 'true',
        'IncludeItemTypes': 'Movie' if kind == 'movie' else 'Series', 'Fields': 'ProviderIds',
        'Limit': 1,
    })
    rows = data.get('Items') if isinstance(data, dict) else None
    return isinstance(rows, list) and any(
        isinstance(item, dict)
        and str(item.get('Id', '')).replace('-', '').lower() == str(item_id).replace('-', '').lower()
        and _has_jellyfin_identity(item, ids)
        for item in rows
    )


def plex_present(server, library, media):
    # Stable provider identifiers, never a title-only match.
    expected = _provider_ids(media).items()
    offset = 0
    deadline = time.monotonic() + 90
    while True:
        if time.monotonic() > deadline: raise MediaRequestError('portal_requests_unavailable')
        data = api(server,'/library/sections/'+quote(str(library['section_id']),safe='')+'/all',
                   params={'includeGuids':1,'X-Plex-Container-Start':offset,'X-Plex-Container-Size':200})
        if not isinstance(data,dict) or not isinstance(data.get('MediaContainer'),dict):
            raise MediaRequestError('portal_requests_unavailable')
        container = data['MediaContainer']
        rows = container.get('Metadata',[]) or []
        for item in rows:
            if time.monotonic() > deadline: raise MediaRequestError('portal_requests_unavailable')
            guids = item.get('Guid',[]) or []
            if _has_plex_identity(item, expected):
                return True
            if not guids and item.get('ratingKey'):
                detail = api(server,'/library/metadata/'+quote(str(item['ratingKey']),safe=''),params={'includeGuids':1})
                item = (detail.get('MediaContainer',{}).get('Metadata') or [{}])[0]
                if _has_plex_identity(item, expected):
                    return True
        offset += len(rows)
        total = container.get('totalSize')
        if not rows or (total is not None and offset >= int(total)) or (total is None and len(rows) < 200): return False


def media_present(server, library, media, kind):
    if str(server['type']).lower() == 'plex': return plex_present(server,library,media)
    expected = _provider_ids(media)
    offset = 0
    deadline = time.monotonic() + 90
    while True:
        if time.monotonic() > deadline: raise MediaRequestError('portal_requests_unavailable')
        data = api(server,'/Items', params={'ParentId':library['section_id'], 'Recursive':'true',
            'IncludeItemTypes':'Movie' if kind == 'movie' else 'Series', 'Fields':'ProviderIds',
            'StartIndex':offset,'Limit':200})
        if not isinstance(data,dict) or not isinstance(data.get('Items'),list):
            raise MediaRequestError('portal_requests_unavailable')
        rows = data['Items']
        for row in rows:
            if _has_jellyfin_identity(row, expected): return True
        offset += len(rows)
        total = data.get('TotalRecordCount')
        if not rows or (total is not None and offset >= int(total)) or (total is None and len(rows) < 200): return False


def arr_defaults(server):
    profiles, roots = parallel_reads([
        lambda: api(server,'/api/v3/qualityprofile'),
        lambda: api(server,'/api/v3/rootfolder')])
    for value in (profiles,roots):
        if isinstance(value,MediaRequestError):
            raise value
    if not isinstance(profiles,list) or not isinstance(roots,list):
        raise MediaRequestError('portal_requests_unavailable')
    if any(not isinstance(r,dict) or type(r.get('id')) is not int for r in profiles + roots):
        raise MediaRequestError('portal_requests_unavailable')
    return {'profiles':profiles, 'roots':roots}


def add_media(server, media, kind, *, choices=None, before_post=None):
    try:
        choices = choices if choices is not None else arr_defaults(server)
    except MediaRequestError as exc:
        exc.before_submission = True
        raise
    settings = json.loads(server.get('settings_json') or '{}').get('media_requests',{})
    profiles, roots = choices['profiles'], choices['roots']
    profile = next((r for r in profiles if r['id'] == settings.get('quality_profile_id')),None)
    root = next((r for r in roots if r['id'] == settings.get('root_folder_id')),None)
    if profile is None and not settings.get('quality_profile_id') and len(profiles) == 1: profile = profiles[0]
    if root is None and not settings.get('root_folder_id') and len(roots) == 1: root = roots[0]
    if not profile or not root or not root.get('path'):
        get_logger('portal_media_requests').warning(
            'ARR request defaults invalid server_id=%s type=%s profile_id=%s root_id=%s profile_found=%s root_found=%s available_profiles=%s available_roots=%s',
            server.get('id'),server.get('type'),settings.get('quality_profile_id'),settings.get('root_folder_id'),
            bool(profile),bool(root and root.get('path')),[r['id'] for r in profiles],[r['id'] for r in roots])
        raise MediaRequestError('portal_requests_not_configured')
    payload = {k:v for k,v in media.items() if k not in ('id','path','qualityProfileId','rootFolderPath','addOptions')}
    payload.update(qualityProfileId=profile['id'], rootFolderPath=root['path'], monitored=True)
    if kind == 'movie': payload['addOptions'] = {'searchForMovie':True}
    else:
        payload.update(seasonFolder=True, seriesType=media.get('seriesType') or 'standard',
            seasons=[{**s,'monitored':s.get('seasonNumber',0) > 0} for s in (media.get('seasons') or [])],
            addOptions={'searchForMissingEpisodes':True})
    if before_post is not None:
        before_post()
    result = api(server,'/api/v3/'+kind,payload=payload)
    if not isinstance(result,dict) or not result.get('id'):
        raise MediaRequestError('portal_requests_unavailable')


def has_saved_request_defaults(server):
    """Tie breaker only: actual defaults are validated on the selected ARR."""
    try:
        defaults = json.loads(server.get('settings_json') or '{}').get('media_requests', {})
        return all(type(defaults.get(key)) is int and defaults[key] > 0
                   for key in ('quality_profile_id', 'root_folder_id'))
    except (TypeError, ValueError, AttributeError):
        return False


def _request_destinations(db, user_id, library_id, kind, backend):
    """Eligible (library, routed services) pairs for one backend, best first."""
    provider = 'radarr' if kind == 'movie' else 'sonarr'
    automatic = library_id is None
    destinations = []
    for candidate in accessible_libraries(db,user_id):
        if not candidate['requests_enabled'] or compatible_arr_type(candidate['type']) != provider: continue
        if not automatic and candidate['id'] != library_id: continue
        linked = linked_arrs(db,candidate,backend)
        if linked: destinations.append((candidate,linked))
    if not destinations:
        raise MediaRequestError('portal_requests_no_libraries' if automatic else 'portal_requests_invalid')
    explicit_library_ids = {candidate['id'] for candidate, _ in destinations
        if db.query_one('SELECT id FROM library_arr_routes WHERE library_id=?', (candidate['id'],))}
    # A fallback must not override an administrator's association. Library
    # preferences apply within each group; media criteria still decide eligibility.
    destinations.sort(key=lambda item: (
        item[0]['id'] not in explicit_library_ids,
        not item[0]['preferred'], item[0]['request_priority'],
        item[0]['id']))
    return destinations, explicit_library_ids


def _eligible_destinations(destinations, metadata, automatic):
    eligible = []
    for candidate, linked in destinations:
        matching = []
        for server in linked:
            # Quality belongs to the ARR profile, not a user resolution.
            conditions = {k:v for k,v in server['conditions'].items() if not automatic or k != 'resolutions'}
            if route_matches_media(conditions,metadata): matching.append(server)
        if matching:
            eligible.append((candidate,linked,matching))
    if not eligible: raise MediaRequestError('portal_requests_no_match')
    return eligible


def _authorized_before_post(db, user_id, library, before_post):
    if before_post is None:
        return None
    backend = request_options(db)[0]
    def authorize_post():
        if request_options(db)[0] != backend:
            raise MediaRequestError('portal_requests_invalid')
        if not any(row['id'] == library['id'] and row['requests_enabled']
                   for row in accessible_libraries(db, user_id)):
            raise MediaRequestError('portal_requests_no_libraries')
        before_post()
    return authorize_post


def submit_request(db,user_id,library_id,kind,external_id,resolution='', *, before_post=None, source='arr',
                   is_4k=None, seasons=None, on_submitted=None, tvdb_choice=None):
    if kind not in ('movie','series') or type(external_id) is not int or external_id <= 0 or resolution not in ('','720p','1080p','2160p'):
        raise MediaRequestError('portal_requests_invalid')
    if source not in ('arr','seerr') or source != request_options(db)[0]:
        raise MediaRequestError('portal_requests_invalid')
    if source == 'seerr':
        return submit_seerr_request(db,user_id,library_id,kind,external_id,resolution,before_post=before_post,
                                    is_4k=is_4k, seasons=seasons, on_submitted=on_submitted,
                                    tvdb_choice=tvdb_choice)
    provider = 'radarr' if kind == 'movie' else 'sonarr'
    automatic = library_id is None
    destinations, explicit_library_ids = _request_destinations(db, user_id, library_id, kind, 'arr')
    get_logger('portal_media_requests').info(
        'ARR request candidates user_id=%s kind=%s destinations=%s', user_id, kind,
        [{'library_id':library['id'], 'server_id':library['server_id'],
          'library_name':library['name'], 'explicit':library['id'] in explicit_library_ids,
          'preferred':bool(library['preferred']), 'library_priority':library['request_priority'],
          'arr_ids':[server['id'] for server in linked]} for library,linked in destinations])
    arrs = list({s['id']:s for _,linked in destinations for s in linked}.values())
    owner = uuid4().hex
    with db.transaction() as cur:
        cur.execute("DELETE FROM portal_media_request_claims WHERE created_at < datetime('now','-5 minutes')")
        cur.execute('INSERT OR IGNORE INTO portal_media_request_claims(kind,external_id,owner) VALUES(?,?,?)',(kind,external_id,owner))
        acquired = cur.rowcount == 1
    if not acquired: raise MediaRequestError('portal_requests_busy')
    deadline_token = _request_deadline.set(time.monotonic() + 120)
    try:
        media = canonical_media(arrs,kind,external_id)
        metadata = {'genres':media.get('genres',[]),'collections':
            [media['collection']['title']] if isinstance(media.get('collection'),dict) and media['collection'].get('title') else [],
            'resolution':resolution}
        eligible = _eligible_destinations(destinations, metadata, automatic)
        # Equal library priorities previously fell back to the database ID,
        # selecting an unconfigured specialized library before a ready one.
        # Never reorder the ARR instances themselves or bypass explicit preferences.
        eligible.sort(key=lambda item: (
            item[0]['id'] not in explicit_library_ids,
            not item[0]['preferred'], item[0]['request_priority'],
            not has_saved_request_defaults(item[2][0]), item[0]['id']))
        library,selected_arrs,matching = eligible[0]
        # Check every registered compatible ARR before scanning media libraries.
        # Routing only controls where we add, never where we detect duplicates.
        registered_arrs = [dict(row) for row in db.query(
            'SELECT * FROM servers WHERE LOWER(type)=? ORDER BY id', (provider,))]
        arr_outcomes = parallel_reads([
            lambda server=server: _arr_contains_media(server, kind, external_id)
            for server in registered_arrs
        ])
        availability = dict(zip((server['id'] for server in registered_arrs), arr_outcomes))
        available_destinations = [(candidate, linked, [server])
            for candidate, linked, candidates in eligible for server in candidates
            if availability.get(server['id']) is False]
        if available_destinations:
            library, selected_arrs, matching = available_destinations[0]
        linked_ids = {server['id'] for server in selected_arrs}
        failed_arr_checks = [
            {'server_id': server['id'], 'server_name': server.get('name'),
             'linked_to_selected_library': server['id'] in linked_ids,
             'destination': server['id'] == matching[0]['id'],
             'endpoint': getattr(outcome, 'endpoint', '/api/v3/' + kind),
             'http_status': getattr(outcome, 'http_status', None),
             'error_type': getattr(outcome, 'connection_error', None) or type(outcome).__name__}
            for server, outcome in zip(registered_arrs, arr_outcomes)
            if isinstance(outcome, MediaRequestError)
        ]
        arr_present = any(outcome is True for outcome in arr_outcomes)

        # Materialize DB rows before dispatching HTTP-only workers. Check all
        # registered media libraries, including those without request routing.
        media_checks = {}
        registered_libraries = [dict(row) for row in db.query("""
            SELECT l.* FROM libraries l JOIN servers s ON s.id=l.server_id
            WHERE LOWER(s.type) IN ('plex','jellyfin') ORDER BY l.id""")]
        for candidate in [library] + [r for r in registered_libraries if r['id'] != library['id']]:
            if compatible_arr_type(candidate['type']) != provider: continue
            media_checks.setdefault(candidate['server_id'], []).append(candidate)

        inventory_hints = _inventory_hints(db, media) if media_checks else {}

        def check_libraries(server, candidates):
            for candidate in candidates:
                hint = inventory_hints.get(candidate['id'])
                if hint is not None:
                    try:
                        if _confirm_inventory_hint(server, candidate, media, kind, hint):
                            return True, False
                    except MediaRequestError:
                        pass  # The regular scan still decides how to handle a provider failure.
            failed = False
            for candidate in candidates:
                try:
                    if media_present(server,candidate,media,kind): return True, failed
                except MediaRequestError:
                    if candidate['id'] == library['id']: failed = True
                    break  # Avoid retrying an unavailable server for every library.
            return False, failed

        jobs = []
        for server_id, candidates in media_checks.items():
            server = dict(db.query_one('SELECT * FROM servers WHERE id=?', (server_id,)))
            jobs.append(lambda server=server, candidates=candidates: check_libraries(server, candidates))
        outcomes = parallel_reads(jobs)
        media_failed = False
        for outcome in outcomes:
            present, failed = outcome
            if present: return 'portal_requests_present'
            media_failed = media_failed or failed
        if arr_present: return 'portal_requests_pending'
        if not available_destinations:
            get_logger('portal_media_requests').error(
                'ARR request has no reachable eligible destination user_id=%s kind=%s external_id=%s library_id=%s destination_arr_id=%s failed_checks=%s',
                user_id, kind, external_id, library['id'], matching[0]['id'], failed_arr_checks)
            raise MediaRequestError('portal_requests_no_arr_available')
        if failed_arr_checks:
            get_logger('portal_media_requests').warning(
                'ARR duplicate checks skipped for unavailable servers user_id=%s kind=%s external_id=%s library_id=%s destination_arr_id=%s failed_checks=%s',
                user_id, kind, external_id, library['id'], matching[0]['id'], failed_arr_checks)
        if media_failed:
            get_logger('portal_media_requests').warning(
                'Media library duplicate check skipped for unavailable server user_id=%s library_id=%s server_id=%s destination_arr_id=%s',
                user_id, library['id'], library['server_id'], matching[0]['id'])
        for library, selected_arrs, matching in available_destinations:
            get_logger('portal_media_requests').info(
                'ARR request destination user_id=%s kind=%s external_id=%s library_id=%s arr_id=%s arr_name=%s explicit=%s arr_priority=%s linked_arr_ids=%s',
                user_id,kind,external_id,library['id'],matching[0]['id'],matching[0].get('name'),
                library['id'] in explicit_library_ids,matching[0]['priority'],[s['id'] for s in selected_arrs])
            try:
                if before_post is None:
                    add_media(matching[0],media,kind)
                else:
                    def authorize_post():
                        if not any(row['id'] == library['id'] and row['requests_enabled']
                                   for row in accessible_libraries(db, user_id)):
                            raise MediaRequestError('portal_requests_no_libraries')
                        before_post()

                    add_media(matching[0],media,kind,before_post=authorize_post)
            except MediaRequestError as exc:
                if not getattr(exc, 'before_submission', False) or str(exc) != 'portal_requests_unavailable':
                    raise
                get_logger('portal_media_requests').warning(
                    'ARR destination skipped before submission user_id=%s library_id=%s arr_id=%s',
                    user_id, library['id'], matching[0]['id'])
                continue
            return 'portal_requests_added'
        get_logger('portal_media_requests').error(
            'ARR request has no destination passing preflight user_id=%s kind=%s external_id=%s',
            user_id, kind, external_id)
        raise MediaRequestError('portal_requests_no_arr_available')
    finally:
        _request_deadline.reset(deadline_token)
        db.execute('DELETE FROM portal_media_request_claims WHERE kind=? AND external_id=? AND owner=?',(kind,external_id,owner))


def _member_identity_keys(db, user_id):
    rows = db.query("SELECT type, external_user_id FROM media_users WHERE vodum_user_id=? AND LOWER(type) IN ('plex','jellyfin')", (user_id,)) or []
    return seerr_user_lookup_keys([dict(row) for row in rows])


def _seerr_details_from(servers, kind, external_id):
    """Details of one title from the first Seerr instance that knows it, with that server's id."""
    for server in servers:
        try:
            candidate = seerr_details(api, server, kind, external_id)
        except MediaRequestError:
            continue
        if isinstance(candidate, dict) and candidate.get('id') == external_id:
            return candidate, server['id']
    raise MediaRequestError('portal_requests_unavailable')


def seerr_season_options(db, user_id, external_id, is_4k=None, tvdb_out=None):
    """Seasons the member may pick for a series, read from a Seerr routed to one of their libraries.

    A dict passed as ``tvdb_out`` receives the TVDB mapping state (see tvdb_options).
    """
    if type(external_id) is not int or external_id <= 0:
        raise MediaRequestError('portal_requests_invalid')
    if request_options(db)[0] != 'seerr':
        raise MediaRequestError('portal_requests_invalid')
    destinations, _ = _request_destinations(db, user_id, None, 'series', 'seerr')
    servers = list({s['id']:s for _,linked in destinations for s in linked}.values())
    deadline_token = _request_deadline.set(time.monotonic() + 15)
    try:
        details, server_id = _seerr_details_from(servers, 'series', external_id)
    finally:
        _request_deadline.reset(deadline_token)
    server = next(s for s in servers if s['id'] == server_id)
    if tvdb_out is not None:
        token = _request_deadline.set(time.monotonic() + 15)
        try:
            tvdb_out.update(tvdb_options(api, server, details, external_id))
        finally:
            _request_deadline.reset(token)
    return seerr_seasons(details, seerr_is_4k(server) if is_4k is None else bool(is_4k))


def submit_seerr_request(db,user_id,library_id,kind,external_id,resolution='', *, before_post=None,
                         is_4k=None, seasons=None, on_submitted=None, tvdb_choice=None):
    """Request through Seerr on behalf of the member; Seerr decides duplicates and approval.

    ``is_4k`` is the member's choice (None when they made none); it only counts
    when their Seerr user may request 4K, otherwise the server flag applies.
    ``seasons`` lists the chosen seasons of a series; None asks for all of them.
    ``tvdb_choice`` is the TVDB series the member picked when Seerr has no TVDB id.
    """
    automatic = library_id is None
    seasons = list(seasons) if kind == 'series' and seasons else None
    destinations, explicit_library_ids = _request_destinations(db, user_id, library_id, kind, 'seerr')
    get_logger('portal_media_requests').info(
        'Seerr request candidates user_id=%s kind=%s destinations=%s', user_id, kind,
        [{'library_id':library['id'], 'library_name':library['name'],
          'explicit':library['id'] in explicit_library_ids, 'seerr_ids':[s['id'] for s in linked]}
         for library,linked in destinations])
    deadline_token = _request_deadline.set(time.monotonic() + 120)
    try:
        servers = list({s['id']:s for _,linked in destinations for s in linked}.values())
        details, details_server_id = _seerr_details_from(servers, kind, external_id)
        metadata = {**seerr_metadata(details), 'resolution': resolution}
        eligible = _eligible_destinations(destinations, metadata, automatic)
        eligible.sort(key=lambda item: (
            item[0]['id'] not in explicit_library_ids,
            not item[0]['preferred'], item[0]['request_priority'], item[0]['id']))
        library, _, matching = eligible[0]
        server = matching[0]
        if server['id'] != details_server_id:
            details = seerr_details(api, server, kind, external_id)
            if not isinstance(details, dict) or details.get('id') != external_id:
                raise MediaRequestError('portal_requests_unavailable')
        seerr_user = None
        def member():
            nonlocal seerr_user
            if seerr_user is None:
                seerr_user = seerr_find_user(api, server, _member_identity_keys(db, user_id))
            if seerr_user is None:
                get_logger('portal_media_requests').info(
                    'Seerr request without matching user user_id=%s seerr_id=%s', user_id, server['id'])
                raise MediaRequestError('portal_requests_seerr_user_missing')
            return seerr_user
        default_4k = seerr_is_4k(server)
        is_4k = bool(is_4k) if is_4k is not None else default_4k
        # A choice that differs from the server flag needs the member's Seerr permission.
        if is_4k != default_4k and not seerr_can_request_4k(member()['permissions'], kind):
            is_4k = default_4k
        state = seerr_media_state(details, is_4k, seasons)
        if state == 'present': return 'portal_requests_present'
        known_tvdb = details_tvdb_id(details) if kind == 'series' else None
        if kind == 'series' and (state == 'pending' or known_tvdb is None):
            # A request the member already made (lost answer, or never handed to Sonarr) is followed, not repeated.
            existing = find_existing_request(api, server, member()['id'], kind, external_id, is_4k)
            if existing is not None and covers_seasons(existing, seasons):
                if on_submitted is not None:
                    on_submitted({'seerr_server_id': server['id'], 'seerr_request_id': existing['id'],
                                  'seerr_state': seerr_request_state(existing), 'is_4k': is_4k, 'seasons': seasons})
                return seerr_request_result(existing) or 'portal_requests_pending'
        if state == 'pending': return 'portal_requests_pending'
        seerr_user = member()
        if default_server_missing(api, server, kind, is_4k):
            get_logger('portal_media_requests').warning(
                'Seerr has no default %s server for 4k=%s seerr_id=%s', 'Sonarr' if kind == 'series' else 'Radarr', is_4k, server['id'])
            raise MediaRequestError('portal_requests_seerr_no_default_server')
        tvdb_id = known_tvdb
        if kind == 'series' and tvdb_id is None:
            try:
                candidates = sonarr_candidates(api, server, external_id)
            except MediaRequestError:
                candidates = []
            outcome, value = resolve_tvdb(candidates, external_id, tvdb_choice)
            if outcome != 'auto':
                get_logger('portal_media_requests').info(
                    'Seerr request without TVDB mapping user_id=%s external_id=%s candidates=%s',
                    user_id, external_id, len(candidates))
                raise MediaRequestError('portal_requests_seerr_tvdb_unresolved')
            tvdb_id = value
        payload = seerr_request_payload(kind, external_id, seerr_user_id=seerr_user['id'], is_4k=is_4k,
                                        tvdb_id=tvdb_id, seasons=seasons)
        get_logger('portal_media_requests').info(
            'Seerr request destination user_id=%s kind=%s external_id=%s library_id=%s seerr_id=%s is_4k=%s seasons=%s',
            user_id,kind,external_id,library['id'],server['id'],is_4k,seasons or 'all')
        authorize = _authorized_before_post(db, user_id, library, before_post)
        if request_options(db)[0] != 'seerr' or not any(row['id'] == server['id'] for row in linked_arrs(db, library, 'seerr')):
            raise MediaRequestError('portal_requests_invalid')
        if authorize is not None:
            authorize()
        if on_submitted is not None:
            # Remember the server before the POST, so a lost answer can be reconciled later.
            on_submitted({'seerr_server_id': server['id'], 'seerr_request_id': None, 'is_4k': is_4k, 'seasons': seasons})
        try:
            created = api(server, '/api/v1/request', payload=payload)
        except MediaRequestError as exc:
            mapped = seerr_error_result(getattr(exc, 'http_status', None))
            if mapped is not None: return mapped
            if str(exc) != 'portal_requests_add_uncertain': raise
            # The answer was lost: the request may exist. Take it over so its status can be followed.
            try:
                created = find_existing_request(api, server, seerr_user['id'], kind, external_id, is_4k)
            except MediaRequestError:
                created = None
            if created is None: raise
        result = seerr_request_result(created)
        if result is None: raise MediaRequestError('portal_requests_unavailable')
        if on_submitted is not None:
            on_submitted({'seerr_server_id': server['id'], 'seerr_request_id': created['id'],
                          'seerr_state': seerr_request_state(created), 'is_4k': is_4k, 'seasons': seasons})
        return result
    finally:
        _request_deadline.reset(deadline_token)
