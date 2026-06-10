from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import requests


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


class ConfiguredHostSession(requests.Session):
    def __init__(self, allowed_origins, default_timeout=None):
        super().__init__()
        self.allowed_origins = {
            origin for origin in allowed_origins if origin is not None
        }
        self.default_timeout = default_timeout

    def request(self, method, url, **kwargs):
        if self.default_timeout is not None:
            kwargs.setdefault("timeout", self.default_timeout)
        return super().request(method, url, **kwargs)

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


def server_http_session(server, allowed_urls=(), default_timeout=None) -> ConfiguredHostSession:
    origins = server_allowed_origins(server)
    origins.update(
        origin for origin in (url_origin(url) for url in allowed_urls) if origin
    )
    return ConfiguredHostSession(origins, default_timeout=default_timeout)


def plex_server_http_session(server, default_timeout=None) -> ConfiguredHostSession:
    return server_http_session(
        server,
        allowed_urls=("https://plex.tv", "https://app.plex.tv"),
        default_timeout=default_timeout,
    )


def servers_http_session(servers, default_timeout=None) -> ConfiguredHostSession:
    origins = set()
    for server in servers:
        origins.update(server_allowed_origins(server))
    return ConfiguredHostSession(origins, default_timeout=default_timeout)
