from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import requests
import json
import time


def url_origin(value: object) -> tuple[str, str, int] | None:
    try:
        parts = urlsplit(str(value or "").strip())
        scheme = parts.scheme.lower()
        hostname = (parts.hostname or "").lower()
        if scheme not in ("http", "https") or not hostname:
            return None
        port = parts.port or (443 if scheme == "https" else 80)
        return scheme, hostname, port
    except ValueError:
        return None


def server_allowed_origins(server) -> set[tuple[str, str, int]]:
    if isinstance(server, dict):
        getter = server.get
    else:
        getter = lambda key: getattr(server, key, None)

    return {
        origin
        for origin in (
            url_origin(getter("url")),
            url_origin(getter("local_url")),
            url_origin(getter("public_url")),
        )
        if origin is not None
    }


def server_verify_tls(server) -> bool:
    if isinstance(server, dict):
        settings_json = server.get("settings_json")
    else:
        settings_json = getattr(server, "settings_json", None)

    try:
        settings = json.loads(settings_json or "{}")
    except (TypeError, ValueError):
        settings = {}
    return settings.get("verify_tls", True) is not False


class ConfiguredHostSession(requests.Session):
    def __init__(self, allowed_origins, default_timeout=None, retry_reads=False):
        super().__init__()
        self.allowed_origins = {
            origin for origin in allowed_origins if origin is not None
        }
        self.default_timeout = default_timeout
        self.retry_reads = retry_reads

    def request(self, method, url, **kwargs):
        origin = url_origin(url)
        if origin is None or origin not in self.allowed_origins:
            raise requests.exceptions.InvalidURL(
                f"Refusing request to an unconfigured server origin: {url}"
            )
        if self.default_timeout is not None:
            kwargs.setdefault("timeout", self.default_timeout)
        # Opt in only for read-only workflows: some Plex GET endpoints mutate state.
        attempts = 3 if self.retry_reads and method.upper() in {"GET", "HEAD"} else 1
        for attempt in range(attempts):
            try:
                response = super().request(method, url, **kwargs)
            except requests.exceptions.SSLError:
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt == attempts - 1:
                    raise
            else:
                if attempt == attempts - 1 or response.status_code not in {502, 503, 504}:
                    return response
                response.close()
            time.sleep(2 ** attempt)

    def get_redirect_target(self, response):
        target = super().get_redirect_target(response)
        if not target:
            return None

        absolute_target = urljoin(response.url, target)
        if url_origin(absolute_target) not in self.allowed_origins:
            raise requests.exceptions.InvalidURL(
                f"Refusing redirect to an unconfigured server origin: {absolute_target}"
            )
        return target


def server_http_session(server, allowed_urls=(), default_timeout=None, retry_reads=False) -> ConfiguredHostSession:
    origins = server_allowed_origins(server)
    origins.update(
        origin for origin in (url_origin(url) for url in allowed_urls) if origin
    )
    session = ConfiguredHostSession(origins, default_timeout=default_timeout, retry_reads=retry_reads)
    session.verify = server_verify_tls(server)
    return session


def plex_server_http_session(server, default_timeout=None, retry_reads=False) -> ConfiguredHostSession:
    return server_http_session(
        server,
        allowed_urls=("https://plex.tv", "https://app.plex.tv"),
        default_timeout=default_timeout,
        retry_reads=retry_reads,
    )


def servers_http_session(servers, default_timeout=None) -> ConfiguredHostSession:
    origins = set()
    for server in servers:
        origins.update(server_allowed_origins(server))
    return ConfiguredHostSession(origins, default_timeout=default_timeout)
