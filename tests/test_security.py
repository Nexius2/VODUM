from __future__ import annotations

import io
import os
import sys
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.archive_safety import validate_zip_limits
from app.config import Config
from app.web.security import get_client_ip, ip_in_networks, is_safe_redirect_target

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    fake_requests = types.ModuleType("requests")

    class FakeSession:
        def get_redirect_target(self, response):
            if getattr(response, "is_redirect", False):
                return response.headers.get("location")
            return None

    fake_requests.Session = FakeSession
    fake_requests.exceptions = types.SimpleNamespace(InvalidURL=ValueError)
    sys.modules["requests"] = fake_requests

from app.core.http_security import (
    ConfiguredHostSession,
    plex_server_http_session,
    server_allowed_origins,
    url_origin,
)


class RedirectSafetyTests(unittest.TestCase):
    def test_accepts_relative_and_same_origin_targets(self):
        host = "https://vodum.example/"

        self.assertTrue(is_safe_redirect_target("/dashboard", host))
        self.assertTrue(is_safe_redirect_target("https://vodum.example/users", host))

    def test_rejects_external_and_scheme_relative_targets(self):
        host = "https://vodum.example/"

        self.assertFalse(is_safe_redirect_target("https://evil.example/", host))
        self.assertFalse(is_safe_redirect_target("//evil.example/", host))
        self.assertFalse(is_safe_redirect_target("javascript:alert(1)", host))


class ProviderRedirectSafetyTests(unittest.TestCase):
    def test_accepts_all_explicitly_configured_remote_origins(self):
        server = {
            "url": "https://jellyfin.example.com",
            "local_url": "http://10.0.0.8:8096",
            "public_url": "https://media.example.net:9443",
        }

        origins = server_allowed_origins(server)
        self.assertIn(url_origin("https://jellyfin.example.com/Users"), origins)
        self.assertIn(url_origin("http://10.0.0.8:8096/System/Ping"), origins)
        self.assertIn(url_origin("https://media.example.net:9443/web"), origins)

    def test_refuses_redirect_to_unconfigured_origin(self):
        session = ConfiguredHostSession(
            {url_origin("https://jellyfin.example.com")}
        )
        response = types.SimpleNamespace(
            url="https://jellyfin.example.com/Users",
            is_redirect=True,
            headers={"location": "https://unknown.example/collect"},
        )

        with self.assertRaisesRegex(Exception, "unconfigured server origin"):
            session.get_redirect_target(response)

    def test_accepts_relative_and_configured_alias_redirects(self):
        session = ConfiguredHostSession(
            {
                url_origin("https://jellyfin.example.com"),
                url_origin("http://10.0.0.8:8096"),
            }
        )
        relative = types.SimpleNamespace(
            url="https://jellyfin.example.com/Users",
            is_redirect=True,
            headers={"location": "/web/"},
        )
        alias = types.SimpleNamespace(
            url="https://jellyfin.example.com/Users",
            is_redirect=True,
            headers={"location": "http://10.0.0.8:8096/web/"},
        )

        self.assertEqual(session.get_redirect_target(relative), "/web/")
        self.assertEqual(
            session.get_redirect_target(alias),
            "http://10.0.0.8:8096/web/",
        )

    def test_plex_session_allows_official_plex_origins(self):
        session = plex_server_http_session(
            {"url": "https://remote-plex.example.com"}
        )
        self.assertIn(url_origin("https://plex.tv/users/account"), session.allowed_origins)
        self.assertIn(url_origin("https://app.plex.tv/desktop"), session.allowed_origins)


class ClientIpTests(unittest.TestCase):
    def test_ignores_untrusted_forwarded_header(self):
        fake_flask = types.SimpleNamespace(
            request=types.SimpleNamespace(
                remote_addr="172.18.0.5",
                headers={"X-Forwarded-For": "127.0.0.1"},
            )
        )
        with patch.dict(sys.modules, {"flask": fake_flask}):
            self.assertEqual(get_client_ip(), "172.18.0.5")

    def test_trusted_proxy_networks_are_explicit(self):
        networks = "127.0.0.1/32,172.18.0.0/16"

        self.assertTrue(ip_in_networks("172.18.0.5", networks))
        self.assertFalse(ip_in_networks("192.168.1.50", networks))
        self.assertFalse(ip_in_networks("invalid", networks))


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.old_members = os.environ.get("VODUM_MAX_ZIP_MEMBERS")
        self.old_size = os.environ.get("VODUM_MAX_ZIP_EXTRACTED_MB")

    def tearDown(self):
        self._restore_env("VODUM_MAX_ZIP_MEMBERS", self.old_members)
        self._restore_env("VODUM_MAX_ZIP_EXTRACTED_MB", self.old_size)

    @staticmethod
    def _restore_env(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    @staticmethod
    def _zip_with_files(contents):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            for name, content in contents:
                zipf.writestr(name, content)
        buffer.seek(0)
        return zipfile.ZipFile(buffer, "r")

    def test_rejects_too_many_members(self):
        os.environ["VODUM_MAX_ZIP_MEMBERS"] = "1"
        with self._zip_with_files([("a", "a"), ("b", "b")]) as zipf:
            with self.assertRaisesRegex(ValueError, "too many entries"):
                validate_zip_limits(zipf)

    def test_rejects_extracted_size_over_limit(self):
        os.environ["VODUM_MAX_ZIP_EXTRACTED_MB"] = "1"
        with self._zip_with_files([("large.bin", b"x" * (1024 * 1024 + 1))]) as zipf:
            with self.assertRaisesRegex(ValueError, "too large after extraction"):
                validate_zip_limits(zipf)


class UploadLimitTests(unittest.TestCase):
    def test_default_limit_accepts_large_tautulli_databases(self):
        self.assertGreaterEqual(Config.MAX_CONTENT_LENGTH, 4 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
