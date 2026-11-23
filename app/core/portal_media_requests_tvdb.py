"""TVDB mapping and request reconciliation for Seerr series requests (fork addition).

Seerr hands a series to Sonarr by TVDB id. When TMDB knows no TVDB id
(``externalIds.tvdbId`` is null) the Seerr UI asks the user to pick the TVDB
series; the portal has to do the same, otherwise the request is created but
never reaches Sonarr. Candidates come from ``GET /api/v1/service/sonarr/lookup/{tmdbId}``.

The second half finds a Seerr request that exists although VODUM never learned
its id (lost POST response), so the portal can follow its status.
"""
from urllib.parse import urlsplit

_POSTER_HOSTS = ('image.tmdb.org', 'artworks.thetvdb.com')
_MAX_CANDIDATES = 30
_REQUEST_PAGE = 50
_REQUEST_PAGES = 6
_REQUEST_DECLINED = 3
_MEDIA_TYPES = {'movie': 'movie', 'series': 'tv'}


def valid_tvdb_id(value):
    return type(value) is int and 0 < value <= 2**31 - 1


def _poster(row):
    urls = []
    if isinstance(row.get('remotePoster'), str):
        urls.append(row['remotePoster'])
    for image in row.get('images') if isinstance(row.get('images'), list) else []:
        if isinstance(image, dict) and image.get('coverType') == 'poster':
            urls.extend(url for url in (image.get('remoteUrl'), image.get('url')) if isinstance(url, str))
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme == 'https' and parts.hostname in _POSTER_HOSTS and not parts.username \
                and not parts.password and parts.port in (None, 443) and len(url) <= 300:
            return url
    return None


def normalize_candidates(data):
    """Unique TVDB candidates ({tvdb_id, tmdb_id, title, year, poster}) from a Sonarr lookup page."""
    rows, seen = [], set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not valid_tvdb_id(item.get('tvdbId')) or item['tvdbId'] in seen:
            continue
        seen.add(item['tvdbId'])
        tmdb_id = item.get('tmdbId')
        year = item.get('year')
        rows.append({'tvdb_id': item['tvdbId'],
                     'tmdb_id': tmdb_id if type(tmdb_id) is int and tmdb_id > 0 else None,
                     'title': str(item.get('title') or '')[:200],
                     'year': year if type(year) is int and year > 0 else None,
                     'poster': _poster(item)})
        if len(rows) >= _MAX_CANDIDATES:
            break
    return rows


def sonarr_candidates(api, server, tmdb_id):
    """TVDB candidates for a TMDB series through the Sonarr instances Seerr knows; [] when none."""
    services = api(server, '/api/v1/service/sonarr')
    if not isinstance(services, list) or not services:
        return []
    return normalize_candidates(api(server, '/api/v1/service/sonarr/lookup/' + str(int(tmdb_id))))


def resolve_tvdb(candidates, tmdb_id, chosen=None):
    """('auto', tvdb_id) | ('choose', candidates) | ('none', []).

    Exactly one candidate carrying the series' own TMDB id is taken over; no or
    several matches leave the decision to the member. A chosen id only counts
    when it is one of the candidates Seerr offered.
    """
    matches = [row for row in candidates if row['tmdb_id'] == tmdb_id]
    if chosen is not None:
        if any(row['tvdb_id'] == chosen for row in candidates):
            return 'auto', chosen
        return 'choose' if candidates else 'none', candidates
    if len(matches) == 1:
        return 'auto', matches[0]['tvdb_id']
    return ('choose', candidates) if candidates else ('none', [])


def details_tvdb_id(details):
    external_ids = details.get('externalIds') if isinstance(details, dict) else None
    value = external_ids.get('tvdbId') if isinstance(external_ids, dict) else None
    return value if valid_tvdb_id(value) else None


def tvdb_options(api, server, details, tmdb_id):
    """What the portal dialog needs: {'state': 'ok'|'auto'|'choose'|'none', 'candidates': [...]}."""
    if details_tvdb_id(details) is not None:
        return {'state': 'ok', 'candidates': []}
    try:
        candidates = sonarr_candidates(api, server, tmdb_id)
    except Exception:
        candidates = []
    state, value = resolve_tvdb(candidates, tmdb_id)
    return {'state': state, 'candidates': value if state == 'choose' else []}


def find_existing_request(api, server, seerr_user_id, kind, tmdb_id, is_4k=False):
    """The member's newest not declined Seerr request for this title, or None.

    Same Seerr user, same TMDB id and media type, same 4K flag.
    """
    media_type = _MEDIA_TYPES[kind]
    skip = 0
    for _ in range(_REQUEST_PAGES):
        data = api(server, '/api/v1/request', params={'take': _REQUEST_PAGE, 'skip': skip, 'filter': 'all',
                                                       'sort': 'added', 'requestedBy': int(seerr_user_id)})
        rows = data.get('results') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict) or type(row.get('id')) is not int:
                continue
            media = row.get('media') if isinstance(row.get('media'), dict) else {}
            owner = row.get('requestedBy') if isinstance(row.get('requestedBy'), dict) else {}
            if media.get('tmdbId') == tmdb_id and media.get('mediaType') == media_type \
                    and bool(row.get('is4k')) == bool(is_4k) and owner.get('id') == seerr_user_id \
                    and row.get('status') != _REQUEST_DECLINED:
                return row
        if len(rows) < _REQUEST_PAGE:
            return None
        skip += _REQUEST_PAGE
    return None


def covers_seasons(request, seasons):
    """Whether an existing request already includes every wanted season (None = all)."""
    have = {row.get('seasonNumber') for row in request.get('seasons') or [] if isinstance(row, dict)}
    if seasons:
        return set(seasons) <= have
    return True


_SERVICES = {'movie': 'radarr', 'series': 'sonarr'}


def default_server_missing(api, server, kind, is_4k=False):
    """True when Seerr has no default Radarr/Sonarr for this tier, so a request would never be handed over.

    Seerr then only logs a warning and the request stays "approved" forever.
    The check is best effort: if the list cannot be read, the request goes ahead.
    """
    try:
        services = api(server, '/api/v1/service/' + _SERVICES[kind])
    except Exception:
        return False
    if not isinstance(services, list):
        return False
    return not any(isinstance(row, dict) and row.get('isDefault') and bool(row.get('is4k')) == bool(is_4k)
                   for row in services)
