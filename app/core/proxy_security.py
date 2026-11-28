from __future__ import annotations

from werkzeug.middleware.proxy_fix import ProxyFix

from web.security import ip_in_networks


class ConditionalProxyFix:
    """Trust forwarded headers only when the direct peer is configured."""
    def __init__(self, wsgi_app, enabled_getter, trusted_networks_getter):
        self._raw_app = wsgi_app
        self._proxy_app = ProxyFix(wsgi_app, x_for=1, x_proto=1, x_host=1)
        self._enabled_getter = enabled_getter
        self._trusted_networks_getter = trusted_networks_getter

    def __call__(self, environ, start_response):
        peer_ip = environ.get("REMOTE_ADDR")
        if self._enabled_getter() and ip_in_networks(peer_ip, self._trusted_networks_getter()):
            return self._proxy_app(environ, start_response)
        return self._raw_app(environ, start_response)
