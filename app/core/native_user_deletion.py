"""Strict, ID-based native deletion with live protection and confirmation."""
import xml.etree.ElementTree as ET
import re
from urllib.parse import quote

from core.http_security import plex_server_http_session, server_http_session
from core.providers.jellyfin_users import _pick_base_url, _headers, _api_key


class NativeDeletionError(RuntimeError):
    pass


def _success(response, expected=(200,)):
    # Do not expose provider bodies, URLs or credentials in task errors.
    if response.status_code not in expected:
        raise NativeDeletionError(f"Provider returned HTTP {response.status_code}")


class NativeUserDeletion:
    def __init__(self, account, server):
        self.account = account
        self.server = server
        self.provider = str(server.get("type") or "").lower()
        self.user_id = str(account.get("external_user_id") or "").strip()
        if not self.user_id or self.user_id == "0":
            raise NativeDeletionError("Missing native user ID; pending invitations are excluded")
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.user_id):
            raise NativeDeletionError("Invalid native user ID")
        if str(account.get("role") or "").lower() in ("owner", "admin", "home"):
            raise NativeDeletionError("Protected owner, administrator or Plex Home account")
        if self.provider == "jellyfin":
            self.session = server_http_session(server)
            self.headers = _headers(_api_key(server))
            self.base = _pick_base_url(server)
        elif self.provider == "plex":
            token = str(server.get("token") or "").strip()
            machine = str(server.get("server_identifier") or "").strip()
            if not token or not machine:
                raise NativeDeletionError("Missing Plex token or server identifier")
            self.session = plex_server_http_session(server)
            self.headers = {"X-Plex-Token": token, "Accept": "application/xml"}
            self.base = f"https://plex.tv/api/servers/{quote(machine, safe='')}/shared_servers"
        else:
            raise NativeDeletionError("Unsupported provider")

    def _get(self, url):
        response = self.session.get(url, headers=self.headers, timeout=20, allow_redirects=False)
        _success(response)
        return response

    def inspect(self):
        """Return exact matching native IDs; malformed/unauthorized responses fail closed."""
        if self.provider == "jellyfin":
            users = self._get(f"{self.base}/Users").json()
            if not isinstance(users, list) or any(not isinstance(u, dict) or not u.get("Id") for u in users):
                raise NativeDeletionError("Invalid Jellyfin users response")
            matches = [u for u in users if str(u["Id"]) == self.user_id]
            if len(matches) > 1:
                raise NativeDeletionError("Ambiguous Jellyfin user ID")
            for user in matches:
                policy = user.get("Policy")
                if not isinstance(policy, dict) or "IsAdministrator" not in policy:
                    raise NativeDeletionError("Cannot verify Jellyfin administrator protection")
                if policy["IsAdministrator"] is not False:
                    raise NativeDeletionError("Jellyfin administrator is protected")
            return [self.user_id] if matches else []

        owner = ET.fromstring(self._get("https://plex.tv/users/account").content)
        if owner.tag.lower() != "user" or not owner.get("id"):
            raise NativeDeletionError("Cannot verify Plex owner")
        if owner.get("id") == self.user_id:
            raise NativeDeletionError("Plex owner is protected")
        root = ET.fromstring(self._get(self.base).content)
        if root.tag != "MediaContainer" or any(node.tag != "SharedServer" for node in root):
            raise NativeDeletionError("Invalid Plex shared users response")
        matches = []
        for node in root:
            native_id = str(node.get("userID") or node.get("userId") or "").strip()
            if not native_id or native_id == "0":
                raise NativeDeletionError("Cannot identify a Plex share; retry after resolving invitations")
            if native_id != self.user_id:
                continue
            if str(node.get("home") or "0").lower() in ("1", "true"):
                raise NativeDeletionError("Plex Home account is protected")
            share_id = str(node.get("id") or "").strip()
            if not share_id.isdigit() or int(share_id) <= 0:
                raise NativeDeletionError("Missing Plex share ID")
            matches.append(share_id)
        return matches

    def delete_and_confirm(self):
        for identifier in self.inspect():
            url = (f"{self.base}/Users/{quote(identifier, safe='')}" if self.provider == "jellyfin"
                   else f"{self.base}/{quote(identifier, safe='')}")
            response = self.session.delete(url, headers=self.headers, timeout=20, allow_redirects=False)
            _success(response, (200, 204, 404))
        if self.inspect():
            raise NativeDeletionError("Native deletion not yet confirmed")

    def close(self):
        self.session.close()
