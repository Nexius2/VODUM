"""User-scoped media search and checked, deterministic ARR submissions."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from uuid import uuid4
from urllib.parse import quote, urlsplit
from core.http_security import server_http_session
from logging_utils import get_logger
from core.library_request_routing import compatible_arr_type, route_matches_media
from core.portal_provider_identity_state import row_media_identity_is_usable

CLAIM_SCHEMA = """CREATE TABLE IF NOT EXISTS portal_media_request_claims (
 kind TEXT NOT NULL, external_id INTEGER NOT NULL, owner TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(kind,external_id)
)"""

_request_deadline = ContextVar('media_request_deadline', default=None)

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
    kind = str(server['type']).lower()
    headers = {'Accept':'application/json'}
    headers['X-Plex-Token' if kind == 'plex' else ('X-Emby-Token' if kind == 'jellyfin' else 'X-Api-Key')] = server.get('token') or ''
    try:
        url = (server.get('url') or server.get('local_url') or server.get('public_url') or '').rstrip('/') + path
        response = http.request('POST' if payload is not None else 'GET', url,
                                params=params, json=payload, headers=headers,
                                timeout=timeout, allow_redirects=False)
        if response.status_code not in (200,201):
            get_logger('portal_media_requests').warning(
                'Media request API failure server_id=%s type=%s method=%s endpoint=%s http=%s',
                server.get('id'),kind,'POST' if payload is not None else 'GET',path,response.status_code)
            raise MediaRequestError('portal_requests_add_failed' if payload is not None else 'portal_requests_unavailable')
        data = response.json()
        if not isinstance(data,(dict,list)): raise MediaRequestError('portal_requests_unavailable')
        return data
    except MediaRequestError:
        raise
    except Exception as exc:
        get_logger('portal_media_requests').warning(
            'Media request API connection failure server_id=%s type=%s method=%s endpoint=%s error_type=%s',
            server.get('id'),kind,'POST' if payload is not None else 'GET',path,type(exc).__name__)
        raise MediaRequestError('portal_requests_add_uncertain' if payload is not None else 'portal_requests_unavailable') from None
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


def linked_arrs(db, library):
    provider = compatible_arr_type(library['type'])
    configured = db.query('SELECT * FROM library_arr_routes WHERE library_id=? ORDER BY priority,arr_server_id', (library['id'],)) or []
    if configured:
        ids = [(r['arr_server_id'],r['priority']) for r in configured if r['enabled']]
    else:
        first = next((row for row in (db.query('SELECT * FROM servers WHERE LOWER(type)=? ORDER BY id', (provider,)) or [])
                      if has_saved_request_defaults(dict(row))), None)
        ids = [(first['id'],1)] if first else []
    result = []
    for arr_id, priority in ids:
        server = db.query_one('SELECT * FROM servers WHERE id=? AND LOWER(type)=?', (arr_id,provider))
        if server and has_saved_request_defaults(dict(server)):
            server = dict(server)
            row = db.query_one('SELECT conditions_json FROM library_arr_conditions WHERE library_id=? AND arr_server_id=?', (library['id'],arr_id))
            server['conditions'] = json.loads(row['conditions_json']) if row else {}
            server['priority'] = priority
            result.append(server)
    return result


def request_libraries(db, user_id):
    return [r for r in accessible_libraries(db,user_id) if r['requests_enabled'] and linked_arrs(db,r)]


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
    for media_kind in kinds:
        provider = 'radarr' if media_kind == 'movie' else 'sonarr'
        servers = {}
        for library in libraries:
            if compatible_arr_type(library['type']) == provider:
                for server in linked_arrs(db,library): servers.setdefault(server['id'],server)
        for server in servers.values():
            identities.append(media_kind)
            jobs.append(lambda server=server, media_kind=media_kind:
                api(server, '/api/v3/' + media_kind + '/lookup', params={'term':term.strip()}))
    if not jobs: raise MediaRequestError('portal_requests_no_libraries')
    results = {media_kind:{} for media_kind in kinds}
    success = False
    for media_kind, rows in zip(identities, parallel_reads(jobs)):
        if not isinstance(rows,list): continue
        success = True
        id_key = 'tmdbId' if media_kind == 'movie' else 'tvdbId'
        for item in rows:
            external_id = item.get(id_key)
            if not isinstance(external_id,int) or external_id <= 0: continue
            results[media_kind].setdefault(external_id, {'external_id':external_id, 'kind':media_kind,
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


def plex_present(server, library, media):
    # Stable provider identifiers, never a title-only match.
    expected = {f'{provider}://{media[key]}' for provider,key in
                [('tmdb','tmdbId'),('tvdb','tvdbId'),('imdb','imdbId')] if media.get(key)}
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
            if not guids and item.get('ratingKey'):
                detail = api(server,'/library/metadata/'+quote(str(item['ratingKey']),safe=''),params={'includeGuids':1})
                guids = (detail.get('MediaContainer',{}).get('Metadata') or [{}])[0].get('Guid',[]) or []
            if expected.intersection(g.get('id') for g in guids): return True
        offset += len(rows)
        total = container.get('totalSize')
        if not rows or (total is not None and offset >= int(total)) or (total is None and len(rows) < 200): return False


def media_present(server, library, media, kind):
    if server['type'] == 'plex': return plex_present(server,library,media)
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
            ids = row.get('ProviderIds') or {}
            if any(media.get(key) and str(ids.get(provider)) == str(media[key]) for provider,key in
                   [('Tmdb','tmdbId'),('Tvdb','tvdbId'),('Imdb','imdbId')]): return True
        offset += len(rows)
        total = data.get('TotalRecordCount')
        if not rows or (total is not None and offset >= int(total)) or (total is None and len(rows) < 200): return False


def arr_defaults(server):
    profiles, roots = parallel_reads([
        lambda: api(server,'/api/v3/qualityprofile'),
        lambda: api(server,'/api/v3/rootfolder')])
    if not isinstance(profiles,list) or not isinstance(roots,list):
        raise MediaRequestError('portal_requests_unavailable')
    if any(not isinstance(r,dict) or type(r.get('id')) is not int for r in profiles + roots):
        raise MediaRequestError('portal_requests_unavailable')
    return {'profiles':profiles, 'roots':roots}


def add_media(server, media, kind):
    choices = arr_defaults(server)
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


def submit_request(db,user_id,library_id,kind,external_id,resolution=''):
    if kind not in ('movie','series') or type(external_id) is not int or external_id <= 0 or resolution not in ('','720p','1080p','2160p'):
        raise MediaRequestError('portal_requests_invalid')
    all_libraries = accessible_libraries(db,user_id)
    provider = 'radarr' if kind == 'movie' else 'sonarr'
    automatic = library_id is None
    destinations = []
    for candidate in all_libraries:
        if not candidate['requests_enabled'] or compatible_arr_type(candidate['type']) != provider: continue
        if not automatic and candidate['id'] != library_id: continue
        linked = linked_arrs(db,candidate)
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
        # Equal library priorities previously fell back to the database ID,
        # selecting an unconfigured specialized library before a ready one.
        # Never reorder the ARR instances themselves or bypass explicit preferences.
        eligible.sort(key=lambda item: (
            item[0]['id'] not in explicit_library_ids,
            not item[0]['preferred'], item[0]['request_priority'],
            not has_saved_request_defaults(item[2][0]), item[0]['id']))
        library,selected_arrs,matching = eligible[0]
        # Materialize DB rows before dispatching HTTP-only workers.
        media_checks = {}
        for candidate in [library] + [r for r in all_libraries if r['id'] != library['id']]:
            if compatible_arr_type(candidate['type']) != provider: continue
            server = dict(db.query_one('SELECT * FROM servers WHERE id=?',(candidate['server_id'],)))
            if candidate['id'] != library['id'] and server.get('status') in ('down','offline'): continue
            media_checks.setdefault(server['id'], []).append((server,candidate))

        def check_libraries(checks):
            failed = False
            for server,candidate in checks:
                try:
                    if media_present(server,candidate,media,kind): return True, failed
                except MediaRequestError:
                    if candidate['id'] == library['id']: failed = True
                    break  # Avoid retrying an unavailable server for every library.
            return False, failed

        jobs = [lambda checks=checks: check_libraries(checks) for checks in media_checks.values()]
        media_count = len(jobs)
        jobs.extend(lambda server=server: api(server,'/api/v3/'+kind) for server in selected_arrs)
        outcomes = parallel_reads(jobs)
        media_failed = False
        for outcome in outcomes[:media_count]:
            present, failed = outcome
            if present: return 'portal_requests_present'
            media_failed = media_failed or failed
        arr_failed = False
        key = 'tmdbId' if kind == 'movie' else 'tvdbId'
        for existing in outcomes[media_count:]:
            if not isinstance(existing,list):
                arr_failed = True
            elif any(r.get(key) == external_id for r in existing):
                return 'portal_requests_pending'
        if media_failed: raise MediaRequestError('portal_requests_media_unavailable')
        if arr_failed: raise MediaRequestError('portal_requests_arr_unavailable')
        get_logger('portal_media_requests').info(
            'ARR request destination user_id=%s kind=%s external_id=%s library_id=%s arr_id=%s arr_name=%s explicit=%s arr_priority=%s linked_arr_ids=%s',
            user_id,kind,external_id,library['id'],matching[0]['id'],matching[0].get('name'),
            library['id'] in explicit_library_ids,matching[0]['priority'],[s['id'] for s in selected_arrs])
        add_media(matching[0],media,kind)
        return 'portal_requests_added'
    finally:
        _request_deadline.reset(deadline_token)
        db.execute('DELETE FROM portal_media_request_claims WHERE kind=? AND external_id=? AND owner=?',(kind,external_id,owner))
