import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.plex_auth_client import (
    PlexAuthClient,
    PlexAuthError,
    PlexPin,
    PlexPinExpired,
)
from core.http_security import ConfiguredHostSession, url_origin


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        return self._call("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._call("GET", url, **kwargs)


class PlexAuthClientTests(unittest.TestCase):
    def test_default_http_session_restricts_redirect_origins(self):
        client = PlexAuthClient("instance-id")
        self.assertIsInstance(client.session, ConfiguredHostSession)
        self.assertIn(url_origin("https://plex.tv"), client.session.allowed_origins)
        self.assertIn(
            url_origin("https://clients.plex.tv"), client.session.allowed_origins
        )
        self.assertNotIn(
            url_origin("https://attacker.example"), client.session.allowed_origins
        )

    def test_pin_url_and_identity_flow(self):
        http = FakeSession(
            FakeResponse({"id": 42, "code": "strong-code", "expiresIn": 300}),
            FakeResponse({"authToken": "top-secret"}),
            FakeResponse({
                "id": 1234,
                "username": "owner",
                "email": "owner@example.test",
                "friendlyName": "The Owner",
            }),
        )
        client = PlexAuthClient("instance-id", version="1.2.3", session=http)
        pin = client.create_pin()
        auth_url = client.build_authorization_url(
            pin, "https://vodum.example.test/auth/plex/callback?state=opaque"
        )
        fragment = parse_qs(urlsplit(auth_url).fragment.removeprefix("?"))
        self.assertEqual(["instance-id"], fragment["clientID"])
        self.assertEqual(["strong-code"], fragment["code"])

        token = client.read_pin_token(pin.id)
        identity = client.fetch_identity(token)
        self.assertEqual("1234", identity.subject)
        self.assertEqual("The Owner", identity.display_name)
        self.assertEqual("true", http.calls[0][2]["params"]["strong"])
        self.assertLessEqual(http.calls[0][2]["timeout"], 30)
        self.assertNotIn("top-secret", repr(identity))

    def test_rejects_unsafe_forward_urls(self):
        client = PlexAuthClient("instance-id", session=FakeSession())
        for value in ("/callback", "javascript:alert(1)", "https://user:pass@host/cb", "https://host/cb#x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.build_authorization_url(PlexPin(1, "code"), value)

    def test_expired_pin_has_safe_error(self):
        client = PlexAuthClient(
            "instance-id", session=FakeSession(FakeResponse({}, status=410))
        )
        with self.assertRaises(PlexPinExpired) as raised:
            client.read_pin_token(42)
        self.assertNotIn("token", str(raised.exception).lower())

    def test_http_error_does_not_include_response_or_secret(self):
        http = FakeSession(FakeResponse({"authToken": "leaked"}, status=500))
        client = PlexAuthClient("instance-id", session=http)
        with self.assertRaises(PlexAuthError) as raised:
            client.read_pin_token(42)
        self.assertNotIn("leaked", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
