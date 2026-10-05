"""Exact-server Plex shares. No matching by display name or borrowed owner token."""
import requests

from core.http_security import ConfiguredHostSession
from core.plex_auth_client import PLEX_HTTP_ORIGINS
from core.plex_share_xml import get_shared_servers_for_machine, plex_title_to_id_map


def activate_plex_server(server, libraries, options, subject, user_token, client_identifier):
    from plexapi.myplex import MyPlexAccount

    machine = str(server.get('server_identifier') or '').strip()
    if not machine or not libraries or not str(subject).isdigit():
        raise ValueError('activation_configuration_error')
    with ConfiguredHostSession(PLEX_HTTP_ORIGINS, default_timeout=10) as http:
        owner = MyPlexAccount(token=server['token'], session=http, timeout=10)
        shares = get_shared_servers_for_machine(owner, machine)  # Fail closed on lookup failure.
        matches = [s for s in shares if str(subject) in
                   (str(s.get('userID') or ''), str(s.get('invitedId') or ''))]
        if len(matches) > 1:
            raise ValueError('activation_configuration_error')
        sections = plex_title_to_id_map(owner, machine)
        ids = [int(sections[library['name']]) for library in libraries]
        headers = {'Accept': 'application/json', 'X-Plex-Product': 'VODUM',
                   'X-Plex-Client-Identifier': client_identifier,
                   'X-Plex-Token': server['token']}
        settings = {key: options.get(key, False) for key in
                    ('allowSync', 'allowCameraUpload', 'allowChannels')}
        settings.update({key: str(options.get(key) or '') for key in
                         ('filterMovies', 'filterTelevision', 'filterMusic')})
        base = 'https://clients.plex.tv/api/v2/shared_servers'
        if matches:
            share_id = str(int(matches[0]['id']))
            response = http.post(f'{base}/{share_id}', headers=headers,
                                 json={'librarySectionIds': ids, 'settings': settings})
        else:
            response = http.post(base, headers=headers, json={
                'machineIdentifier': machine, 'invitedId': int(subject),
                'librarySectionIds': ids, 'settings': settings,
            })
        response.raise_for_status()
        # Re-read after POST, including a prior POST whose response was lost.
        shares = get_shared_servers_for_machine(owner, machine)
        matching_ids = {str(s['id']) for s in shares if str(subject) in
                        (str(s.get('userID') or ''), str(s.get('invitedId') or ''))}
        if not matching_ids:
            return 'pending'
        headers['X-Plex-Token'] = user_token
        try:
            response = http.get(f'{base}/invites/received/pending', headers=headers)
            response.raise_for_status()
            for invitation in response.json():
                for share in invitation.get('sharedServers') or []:
                    # Never accept the first invitation or all invitations from an owner.
                    if str(share.get('id')) in matching_ids:
                        accepted = http.post(f"{base}/{int(share['id'])}/accept", headers=headers)
                        accepted.raise_for_status()
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            # User may need to accept in Plex; readiness must still be verified below.
            pass
        response = http.get('https://plex.tv/api/v2/resources', headers=headers,
                            params={'includeHttps': 1, 'includeRelay': 1})
        response.raise_for_status()
        return 'ready' if any(str(r.get('clientIdentifier')) == machine
                              and 'server' in str(r.get('provides') or '')
                              for r in response.json()) else 'pending'
