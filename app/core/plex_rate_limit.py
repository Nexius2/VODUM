import time
import threading
import requests
from collections import deque


_LOCK = threading.Lock()
_LAST_REQUEST_AT = {}
_WAITERS = {}
_SLOT_CHANGED = threading.Condition(_LOCK)
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


def wait_for_plex_slot(server_or_url, heartbeat=None, priority=False) -> None:
    key = _normalize_server_key(server_or_url)
    if not key:
        return
    # FIFO admission: monitoring must not repeatedly win the same slot while a
    # collection waits. The aggregate rate remains one request/second/server.
    ticket = (bool(priority),object())
    started=time.monotonic()
    with _SLOT_CHANGED:
        queue = _WAITERS.setdefault(key,deque())
        if priority:
            position=next((i for i,item in enumerate(queue) if not item[0]),len(queue))
            queue.insert(position,ticket)
        else:queue.append(ticket)
    try:
        while True:
            if heartbeat is not None:
                heartbeat()
            with _SLOT_CHANGED:
                now = time.monotonic()
                remaining = _MIN_INTERVAL-(now-_LAST_REQUEST_AT.get(key,0.0))
                if queue[0] is ticket and remaining<=0:
                    _LAST_REQUEST_AT[key] = now
                    return time.monotonic()-started
                _SLOT_CHANGED.wait(timeout=min(max(remaining,0.01),0.5) if queue[0] is ticket else 0.5)
    finally:
        with _SLOT_CHANGED:
            queue.remove(ticket)
            if not queue:
                _WAITERS.pop(key,None)
            _SLOT_CHANGED.notify_all()


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
        priority=getattr(session,'_vodum_request_priority',False)
        waited=wait_for_plex_slot(server_key,heartbeat=getattr(session,'_vodum_before_request',None),
            priority=priority() if callable(priority) else bool(priority))
        on_wait=getattr(session,'_vodum_on_wait',None)
        if callable(on_wait) and isinstance(waited,(int,float)):on_wait(waited)
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
