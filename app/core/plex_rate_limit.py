import time
import threading
import requests


_LOCK = threading.Lock()
_LAST_REQUEST_AT = {}
_MIN_INTERVAL = 1.0  # 1 requête / seconde / serveur


def _normalize_server_key(server_or_url) -> str:
    if isinstance(server_or_url, dict):
        raw = (
            server_or_url.get("url")
            or server_or_url.get("local_url")
            or server_or_url.get("public_url")
            or ""
        )
    else:
        raw = str(server_or_url or "")

    raw = raw.strip().rstrip("/")
    return raw.lower()


def wait_for_plex_slot(server_or_url) -> None:
    key = _normalize_server_key(server_or_url)
    if not key:
        return

    while True:
        with _LOCK:
            now = time.monotonic()
            last = _LAST_REQUEST_AT.get(key, 0.0)
            remaining = _MIN_INTERVAL - (now - last)

            if remaining <= 0:
                _LAST_REQUEST_AT[key] = now
                return

        time.sleep(remaining)


def install_plex_rate_limit(session: requests.Session, server_or_url):
    """
    Wrap session.request pour imposer 1 requête / seconde / serveur Plex.
    """
    if not session or not hasattr(session, "request"):
        return session

    if getattr(session, "_vodum_plex_rate_limit_installed", False):
        return session

    server_key = _normalize_server_key(server_or_url)
    original_request = session.request

    def wrapped_request(method, url, **kwargs):
        wait_for_plex_slot(server_key)
        return original_request(method, url, **kwargs)

    session.request = wrapped_request
    session._vodum_plex_rate_limit_installed = True
    session._vodum_plex_rate_limit_key = server_key
    return session


def plex_get(server_or_url, path: str, **kwargs):
    base = str(server_or_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("Missing Plex base URL")

    wait_for_plex_slot(base)
    return requests.get(f"{base}{path}", **kwargs)


def plex_request(method: str, server_or_url, path: str, **kwargs):
    base = str(server_or_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("Missing Plex base URL")

    wait_for_plex_slot(base)
    return requests.request(method, f"{base}{path}", **kwargs)