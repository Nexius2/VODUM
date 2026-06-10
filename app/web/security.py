from __future__ import annotations

import ipaddress
from urllib.parse import urljoin, urlsplit


def get_client_ip() -> str:
    """
    Return the client address resolved by the WSGI stack.

    ProxyFix already rewrites REMOTE_ADDR when proxy trust is enabled. Reading
    X-Forwarded-For again here would allow clients to influence the IP filter.
    """
    from flask import request

    return (request.remote_addr or "").strip()


def ip_in_networks(ip_value: str | None, networks_value: str | None) -> bool:
    try:
        ip = ipaddress.ip_address((ip_value or "").strip())
    except ValueError:
        return False

    for raw_network in (networks_value or "").split(","):
        raw_network = raw_network.strip()
        if not raw_network:
            continue
        try:
            if ip in ipaddress.ip_network(raw_network, strict=False):
                return True
        except ValueError:
            continue

    return False


def is_safe_redirect_target(target: str | None, host_url: str) -> bool:
    if not target:
        return False

    try:
        host = urlsplit(host_url)
        resolved = urlsplit(urljoin(host_url, target))
    except Exception:
        return False

    return (
        resolved.scheme in ("http", "https")
        and resolved.scheme == host.scheme
        and resolved.netloc == host.netloc
    )


def safe_redirect_target(target: str | None, fallback: str) -> str:
    from flask import request

    if is_safe_redirect_target(target, request.host_url):
        return str(target)
    return fallback
