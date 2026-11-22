"""Server-bound Jellyfin Quick Connect for the singleton VODUM administrator."""
import json
import uuid
from urllib.parse import urlsplit

import requests

from core.http_security import server_http_session


class JellyfinAdminAuthError(ValueError):
    pass


class JellyfinApprovalPending(JellyfinAdminAuthError):
    pass


def normalize_server_url(value):
    raw = str(value or '').strip().rstrip('/')
    try:
        parts = urlsplit(raw)
        if (parts.scheme not in {'http', 'https'} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or parts.port == 0
                or any(ord(c) < 33 for c in raw) or '\\' in raw or len(raw) > 2048):
            raise ValueError()
    except ValueError as exc:
        raise JellyfinAdminAuthError('jellyfin_admin_invalid_url') from exc
    return raw


def encode_binding(url, server_id, user_id):
    # The identity is a tuple: URL + immutable server ID + immutable user ID.
    # User names are display-only and never authorize a login.
    return json.dumps([normalize_server_url(url), str(server_id), str(user_id)], separators=(',', ':'))


def decode_binding(subject):
    try:
        binding = json.loads(subject)
        if not isinstance(binding, list) or len(binding) != 3:
            raise ValueError()
        url, server_id, user_id = binding
        if not isinstance(server_id, str) or not server_id or not isinstance(user_id, str) or not user_id:
            raise ValueError()
        return normalize_server_url(url), server_id, user_id
    except (TypeError, ValueError) as exc:
        raise JellyfinAdminAuthError('jellyfin_admin_failed') from exc


class JellyfinQuickConnectClient:
    def __init__(self, url, device_id=None):
        self.url = normalize_server_url(url)
        self.device_id = device_id or uuid.uuid4().hex
        if not str(self.device_id).isalnum() or len(str(self.device_id)) > 64:
            raise JellyfinAdminAuthError('jellyfin_admin_failed')
        self.http = server_http_session({'url': self.url}, default_timeout=10)
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'MediaBrowser Client="VODUM Admin", Device="Web", DeviceId="{self.device_id}", Version="1"',
        }

    def close(self):
        self.http.close()

    def _request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, self.url + path, headers=self.headers,
                                         allow_redirects=False, **kwargs)
            try:
                if not 200 <= response.status_code < 300:
                    raise JellyfinAdminAuthError('jellyfin_admin_failed')
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError()
                return payload
            finally:
                response.close()
        except (requests.RequestException, ValueError, TypeError) as exc:
            if isinstance(exc, JellyfinAdminAuthError):
                raise
            raise JellyfinAdminAuthError('jellyfin_admin_failed') from exc

    def start(self):
        info = self._request('GET', '/System/Info/Public')
        pin = self._request('POST', '/QuickConnect/Initiate')
        server_id = str(info.get('Id') or '')
        code, secret = str(pin.get('Code') or ''), str(pin.get('Secret') or '')
        if not server_id or not secret or len(code) != 6 or not code.isalnum():
            raise JellyfinAdminAuthError('jellyfin_admin_failed')
        return {'server_id': server_id, 'code': code, 'secret': secret,
                'device_id': self.device_id}

    def finish(self, secret, expected_server_id):
        state = self._request('GET', '/QuickConnect/Connect', params={'secret': secret})
        if state.get('Authenticated') is not True:
            raise JellyfinApprovalPending('jellyfin_admin_pending')
        auth = self._request('POST', '/Users/AuthenticateWithQuickConnect', json={'Secret': secret})
        token = str(auth.get('AccessToken') or '')
        if not token or any(ord(c) < 32 or c in '\\"' for c in token):
            raise JellyfinAdminAuthError('jellyfin_admin_failed')
        self.headers['Authorization'] += f', Token="{token}"'
        user = self._request('GET', '/Users/Me')
        info = self._request('GET', '/System/Info/Public')
        policy = user.get('Policy')
        auth_user = auth.get('User')
        if not isinstance(policy, dict) or not isinstance(auth_user, dict):
            raise JellyfinAdminAuthError('jellyfin_admin_failed')
        if (str(info.get('Id') or '') != expected_server_id
                or str(auth.get('ServerId') or '') != expected_server_id
                or not user.get('Id') or user.get('Id') != auth_user.get('Id')
                or policy.get('IsAdministrator') is not True or policy.get('IsDisabled') is True):
            raise JellyfinAdminAuthError('jellyfin_admin_account_required')
        return {'subject': encode_binding(self.url, expected_server_id, user['Id']),
                'name': str(user.get('Name') or ''), 'token': token}
