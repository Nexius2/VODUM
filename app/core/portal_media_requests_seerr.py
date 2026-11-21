"""Seerr (Overseerr/Jellyseerr) search and requests on behalf of a portal member.

Seerr owns duplicate detection, approval and quotas. VODUM only maps the member
to a Seerr user, reads the media status it reports and submits the request.
"""
from urllib.parse import quote

SEERR_POSTER_BASE = 'https://image.tmdb.org/t/p/w300'
# Seerr MediaStatus: 1 unknown, 2 pending, 3 processing, 4 partially available, 5 available.
_STATUS_PENDING = (2, 3)
_STATUS_AVAILABLE = (5,)
# Seerr MediaRequestStatus: 1 pending approval, 2 approved, 3 declined.
_REQUEST_PENDING_APPROVAL = 1
_SEERR_KINDS = {'movie': 'movie', 'series': 'tv'}
_USER_PAGE = 100


def seerr_media_type(kind):
    return _SEERR_KINDS[kind]


def seerr_poster_url(poster_path):
    path = str(poster_path or '').strip()
    if not path.startswith('/') or '..' in path or len(path) > 200:
        return None
    return SEERR_POSTER_BASE + quote(path, safe='/')


def _year(value):
    text = str(value or '')[:4]
    return int(text) if text.isdigit() else None


def seerr_search_rows(data, kinds):
    """Normalize a Seerr search page into portal rows, keeping Seerr's order."""
    results = data.get('results') if isinstance(data, dict) else None
    rows = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        media_type = item.get('mediaType')
        kind = 'movie' if media_type == 'movie' else 'series' if media_type == 'tv' else None
        external_id = item.get('id')
        if kind not in kinds or type(external_id) is not int or external_id <= 0:
            continue
        rows.append({'source': 'seerr', 'external_id': external_id, 'kind': kind,
                     'title': item.get('title') or item.get('name') or '',
                     'year': _year(item.get('releaseDate') or item.get('firstAirDate')),
                     'overview': item.get('overview') or '',
                     'poster': seerr_poster_url(item.get('posterPath'))})
    return rows


def seerr_metadata(details):
    """Routing criteria from Seerr details; Seerr has no resolution of its own."""
    genres = [g.get('name') for g in (details.get('genres') or []) if isinstance(g, dict) and g.get('name')]
    collection = details.get('collection')
    collections = [collection['name']] if isinstance(collection, dict) and collection.get('name') else []
    return {'genres': genres, 'collections': collections}


def seerr_media_state(details, is_4k=False):
    """'present', 'pending' or None from the status Seerr already tracks."""
    info = details.get('mediaInfo') if isinstance(details, dict) else None
    if not isinstance(info, dict):
        return None
    status = info.get('status4k' if is_4k else 'status')
    if status in _STATUS_AVAILABLE:
        return 'present'
    if status in _STATUS_PENDING:
        return 'pending'
    return None


def seerr_user_lookup_keys(media_users):
    """Provider identities of one VODUM user, as Seerr stores them."""
    keys = {'plex': set(), 'jellyfin': set()}
    for row in media_users:
        provider = str(row.get('type') or '').strip().lower()
        external = str(row.get('external_user_id') or '').strip()
        if provider in keys and external:
            keys[provider].add(external)
    return keys


def match_seerr_user(users, keys):
    """Return the Seerr user id for the member's Plex or Jellyfin identity, or None."""
    for user in users:
        if not isinstance(user, dict) or type(user.get('id')) is not int:
            continue
        plex_id = user.get('plexId')
        if plex_id is not None and str(plex_id) in keys.get('plex', ()):
            return user['id']
        jellyfin_id = str(user.get('jellyfinUserId') or '').replace('-', '').lower()
        if jellyfin_id and jellyfin_id in {v.replace('-', '').lower() for v in keys.get('jellyfin', ())}:
            return user['id']
    return None


def seerr_request_payload(kind, external_id, *, seerr_user_id, is_4k=False, tvdb_id=None):
    payload = {'mediaType': seerr_media_type(kind), 'mediaId': int(external_id),
               'userId': int(seerr_user_id), 'is4k': bool(is_4k)}
    if kind == 'series':
        payload['seasons'] = 'all'
        if type(tvdb_id) is int and tvdb_id > 0:
            payload['tvdbId'] = tvdb_id
    return payload


def seerr_request_result(created):
    """Map a created Seerr request to a portal result key."""
    if not isinstance(created, dict) or type(created.get('id')) is not int:
        return None
    if created.get('status') == _REQUEST_PENDING_APPROVAL:
        return 'portal_requests_seerr_awaiting_approval'
    return 'portal_requests_added'


def seerr_error_result(http_status):
    """Portal result for a rejected POST; Seerr reports duplicates and quotas itself."""
    if http_status == 409:
        return 'portal_requests_pending'
    if http_status == 403:
        return 'portal_requests_seerr_rejected'
    return None


def seerr_is_4k(server):
    import json
    try:
        settings = json.loads(server.get('settings_json') or '{}').get('media_requests', {})
    except (TypeError, ValueError, AttributeError):
        return False
    return bool(isinstance(settings, dict) and settings.get('is_4k'))


def seerr_search(api, server, term, kinds):
    data = api(server, '/api/v1/search', params={'query': term, 'page': 1})
    return seerr_search_rows(data, kinds)


def seerr_details(api, server, kind, external_id):
    return api(server, '/api/v1/' + seerr_media_type(kind) + '/' + str(int(external_id)))


def seerr_find_user(api, server, keys):
    skip = 0
    while True:
        data = api(server, '/api/v1/user', params={'take': _USER_PAGE, 'skip': skip})
        users = data.get('results') if isinstance(data, dict) else None
        if not isinstance(users, list):
            return None
        found = match_seerr_user(users, keys)
        if found is not None or len(users) < _USER_PAGE:
            return found
        skip += _USER_PAGE
        if skip >= 10000:
            return None
