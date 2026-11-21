"""Seerr (Overseerr/Jellyseerr) search and requests on behalf of a portal member.

Seerr owns duplicate detection, approval and quotas. VODUM only maps the member
to a Seerr user, reads the media status it reports and submits the request.
"""
from urllib.parse import quote

SEERR_POSTER_BASE = 'https://image.tmdb.org/t/p/w300'
# Seerr MediaStatus: 1 unknown, 2 pending, 3 processing, 4 partially available, 5 available.
_STATUS_PENDING = (2, 3)
_STATUS_PARTIAL = (4,)
_STATUS_AVAILABLE = (5,)
_BADGES = {2: 'pending', 3: 'pending', 4: 'partial', 5: 'available'}
# Seerr MediaRequestStatus: 1 pending approval, 2 approved, 3 declined, 4 failed, 5 completed.
_REQUEST_PENDING_APPROVAL = 1
_REQUEST_APPROVED = 2
_REQUEST_DECLINED = 3
_REQUEST_FAILED = 4
_REQUEST_COMPLETED = 5
# Seerr permission bits (server/lib/permissions.ts); ADMIN implies everything.
PERMISSION_ADMIN = 2
PERMISSION_REQUEST_4K = 1024
PERMISSION_REQUEST_4K_MOVIE = 2048
PERMISSION_REQUEST_4K_TV = 4096
_SEERR_KINDS = {'movie': 'movie', 'series': 'tv'}
_USER_PAGE = 100
MAX_SEASONS = 100
FINAL_REQUEST_STATES = ('declined', 'failed', 'available')


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


def seerr_status_badge(status):
    """Portal badge key ('available', 'partial', 'pending') for a Seerr MediaStatus, or None."""
    return _BADGES.get(status) if type(status) is int else None


def seerr_media_badges(item):
    """(badge, badge_4k) from the mediaInfo Seerr attaches to search results and details."""
    info = item.get('mediaInfo') if isinstance(item, dict) else None
    if not isinstance(info, dict):
        return None, None
    return seerr_status_badge(info.get('status')), seerr_status_badge(info.get('status4k'))


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
        badge, badge_4k = seerr_media_badges(item)
        rows.append({'source': 'seerr', 'external_id': external_id, 'kind': kind,
                     'title': item.get('title') or item.get('name') or '',
                     'year': _year(item.get('releaseDate') or item.get('firstAirDate')),
                     'overview': item.get('overview') or '',
                     'poster': seerr_poster_url(item.get('posterPath')),
                     'status': badge, 'status_4k': badge_4k})
    return rows


def seerr_metadata(details):
    """Routing criteria from Seerr details; Seerr has no resolution of its own."""
    genres = [g.get('name') for g in (details.get('genres') or []) if isinstance(g, dict) and g.get('name')]
    collection = details.get('collection')
    collections = [collection['name']] if isinstance(collection, dict) and collection.get('name') else []
    return {'genres': genres, 'collections': collections}


def _season_states(details, is_4k):
    """{season_number: MediaStatus} from the per-season status Seerr tracks."""
    info = details.get('mediaInfo') if isinstance(details, dict) else None
    rows = info.get('seasons') if isinstance(info, dict) else None
    states = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and type(row.get('seasonNumber')) is int:
            states[row['seasonNumber']] = row.get('status4k' if is_4k else 'status')
    return states


def seerr_media_state(details, is_4k=False, seasons=None):
    """'present', 'pending' or None from the status Seerr already tracks.

    With an explicit season list the per-season status decides: the request is
    pointless only when every chosen season is already available or in progress.
    """
    info = details.get('mediaInfo') if isinstance(details, dict) else None
    if not isinstance(info, dict):
        return None
    if seasons:
        states = _season_states(details, is_4k)
        chosen = [states.get(number) for number in seasons]
        if all(status in _STATUS_AVAILABLE for status in chosen):
            return 'present'
        if all(status in _STATUS_AVAILABLE + _STATUS_PENDING + _STATUS_PARTIAL for status in chosen):
            return 'pending'
        return None
    status = info.get('status4k' if is_4k else 'status')
    if status in _STATUS_AVAILABLE:
        return 'present'
    if status in _STATUS_PENDING:
        return 'pending'
    return None


def seerr_seasons(details, is_4k=False):
    """Requestable seasons of a series with the status Seerr knows for each.

    Specials (season 0) are left out, as Seerr's own request dialog does.
    A season already available or in progress is listed but marked, so the
    portal can show it and leave it out of the default selection.
    """
    states = _season_states(details, is_4k)
    rows = []
    seasons = details.get('seasons') if isinstance(details, dict) else None
    for season in seasons if isinstance(seasons, list) else []:
        if not isinstance(season, dict):
            continue
        number = season.get('seasonNumber')
        if type(number) is not int or number <= 0:
            continue
        badge = seerr_status_badge(states.get(number))
        episodes = season.get('episodeCount')
        rows.append({'number': number, 'name': str(season.get('name') or '')[:80],
                     'episodes': episodes if type(episodes) is int else None,
                     'status': badge, 'requestable': badge not in ('available', 'pending')})
    rows.sort(key=lambda row: row['number'])
    return rows[:MAX_SEASONS]


def parse_season_selection(value):
    """Season numbers from a form field; None means every season (the default)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = [part for part in value.replace(';', ',').split(',') if part.strip()]
    if not isinstance(value, (list, tuple)):
        raise ValueError('seasons')
    seasons = []
    for part in value:
        text = str(part).strip()
        if not text.isdigit() or len(text) > 4:
            raise ValueError('seasons')
        number = int(text)
        if 0 < number and number not in seasons:
            seasons.append(number)
    if len(seasons) > MAX_SEASONS:
        raise ValueError('seasons')
    return sorted(seasons) or None


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
    """Return the Seerr user ({'id', 'permissions'}) for the member's Plex or Jellyfin identity, or None."""
    jellyfin_keys = {v.replace('-', '').lower() for v in keys.get('jellyfin', ())}
    for user in users:
        if not isinstance(user, dict) or type(user.get('id')) is not int:
            continue
        plex_id = user.get('plexId')
        matched = plex_id is not None and str(plex_id) in keys.get('plex', ())
        if not matched:
            jellyfin_id = str(user.get('jellyfinUserId') or '').replace('-', '').lower()
            matched = bool(jellyfin_id) and jellyfin_id in jellyfin_keys
        if matched:
            permissions = user.get('permissions')
            return {'id': user['id'], 'permissions': permissions if type(permissions) is int else 0}
    return None


def seerr_can_request_4k(permissions, kind):
    """Whether Seerr lets this user ask for 4K versions of movies or series."""
    if type(permissions) is not int or permissions < 0:
        return False
    specific = PERMISSION_REQUEST_4K_MOVIE if kind == 'movie' else PERMISSION_REQUEST_4K_TV
    return bool(permissions & (PERMISSION_ADMIN | PERMISSION_REQUEST_4K | specific))


def seerr_request_payload(kind, external_id, *, seerr_user_id, is_4k=False, tvdb_id=None, seasons=None):
    payload = {'mediaType': seerr_media_type(kind), 'mediaId': int(external_id),
               'userId': int(seerr_user_id), 'is4k': bool(is_4k)}
    if kind == 'series':
        payload['seasons'] = [int(number) for number in seasons] if seasons else 'all'
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


def seerr_request_state(data):
    """Portal tracking state of one Seerr request from GET /api/v1/request/{id}.

    Approval comes first; once approved, the media status says whether the
    download finished. 'declined', 'failed' and 'available' are final.
    """
    if not isinstance(data, dict) or type(data.get('id')) is not int:
        return None
    status = data.get('status')
    if status == _REQUEST_DECLINED:
        return 'declined'
    if status == _REQUEST_FAILED:
        return 'failed'
    if status == _REQUEST_COMPLETED:
        return 'available'
    if status == _REQUEST_PENDING_APPROVAL:
        return 'pending_approval'
    if status != _REQUEST_APPROVED:
        return None
    media = data.get('media')
    media_status = media.get('status4k' if data.get('is4k') else 'status') if isinstance(media, dict) else None
    if media_status in _STATUS_AVAILABLE:
        return 'available'
    if media_status in _STATUS_PARTIAL:
        return 'partial'
    return 'approved'


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


def seerr_search_path(term):
    """Seerr rejects '+' for spaces in the query (HTTP 400); it wants percent-encoding."""
    return '/api/v1/search?query=' + quote(str(term), safe='') + '&page=1'


def seerr_search(api, server, term, kinds):
    data = api(server, seerr_search_path(term))
    return seerr_search_rows(data, kinds)


def seerr_details(api, server, kind, external_id):
    return api(server, '/api/v1/' + seerr_media_type(kind) + '/' + str(int(external_id)))


def seerr_request_status(api, server, request_id):
    return seerr_request_state(api(server, '/api/v1/request/' + str(int(request_id))))


def seerr_find_user(api, server, keys):
    """The member's Seerr user as {'id', 'permissions'}, or None."""
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
