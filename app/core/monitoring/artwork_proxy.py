"""Fetch monitoring artwork from configured media servers with disk-cache fallback."""

from __future__ import annotations
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from itertools import product
from urllib.parse import urlsplit
import threading
import time

import requests
from urllib3.util import Timeout
from core.jellyfin_auth import jellyfin_headers

import re
from logging_utils import get_logger

from core.http_security import server_http_session
from core.monitoring.artwork_cache import (
    artwork_cache_key, detect_image_content_type, read_artwork_cache, write_artwork_cache,
)
from core.plex_rate_limit import wait_for_plex_slot

logger = get_logger("artwork_proxy")

_MAX_BACKGROUND_REFRESHES = 2
_REFRESH_RETRY_SECONDS = 30
_REFRESH_POOL = ThreadPoolExecutor(max_workers=_MAX_BACKGROUND_REFRESHES, thread_name_prefix="artwork")
_FETCH_LOCK = threading.Lock()
_IN_FLIGHT = {}
_BACKGROUND_KEYS = set()
_BACKGROUND_RETRY_AT = OrderedDict()


def _log_artwork_failure(server, exc):
    # Do not log exception text or request URLs: they may contain credentials.
    response = getattr(exc, "response", None)
    logger.warning(
        "Artwork fetch failed: provider=%s server_id=%s error=%s http_status=%s",
        server.get("type"), server.get("id"), type(exc).__name__,
        getattr(response, "status_code", None),
    )


class ArtworkProxyError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _safe_relative_media_path(path: str) -> bool:
    path = str(path or "").strip()
    return bool(path and path.startswith("/") and "://" not in path and not path.startswith("//") and ".." not in path and "\\" not in path)


def _server_bases(server: dict) -> list[str]:
    bases = []
    for key in ("url", "local_url", "public_url"):
        value = str(server.get(key) or "").strip().rstrip("/")
        if value and value not in bases:
            bases.append(value)
    return bases


def _cached_result(cache_key: str, allow_stale: bool = False) -> dict | None:
    cached = read_artwork_cache(cache_key, allow_stale=allow_stale)
    return {"kind": "file", **cached} if cached else None


def _content_result(cache_key: str, response) -> dict:
    content_type = response.headers.get("Content-Type") or ""
    if not write_artwork_cache(cache_key, response.content, content_type):
        raise ValueError("Provider response is not a supported image")
    cached = read_artwork_cache(cache_key)
    return {
        "kind": "content",
        "content": response.content,
        "content_type": cached["content_type"] if cached else "image/jpeg",
    }


def _plex_candidate_paths(path: str) -> list[str]:
    """Return safe fallbacks for Plex's expiring/versioned artwork paths."""
    path = str(path or "").strip()
    candidates = [path]

    match = re.fullmatch(
        r"(/library/metadata/[^/]+)/(thumb|art)(?:/[^/?#]+)?",
        path,
        flags=re.IGNORECASE,
    )
    if match:
        media_path, image_kind = match.groups()
        candidates.append(f"{media_path}/{image_kind}")
        if image_kind.lower() == "art":
            candidates.append(f"{media_path}/thumb")
    elif path.endswith("/art"):
        candidates.append(path[:-4] + "/thumb")

    return list(dict.fromkeys(candidates))


def _fetch_artwork_candidates(server, provider, cache_key, bases, paths, token, timeout, **request_options):
    deadline = time.monotonic() + timeout
    http = server_http_session(server)
    try:
        for path, base in product(paths, bases):
            if time.monotonic() >= deadline:
                break
            if provider == "plex":
                try:
                    wait_for_plex_slot(base, deadline=deadline)
                except TimeoutError:
                    break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                headers = {"X-Plex-Token": token} if provider == "plex" else jellyfin_headers(token)
                response = http.get(
                    base + path, headers=headers, timeout=Timeout(total=remaining), **request_options,
                )
                response.raise_for_status()
                return _content_result(cache_key, response)
            except Exception as exc:
                _log_artwork_failure(server, exc)
    finally:
        http.close()
    raise ArtworkProxyError(502, f"{'Plex' if provider == 'plex' else 'Jellyfin'} artwork unavailable")


def _complete_fetch(cache_key, pending, fetch, *, background=False):
    # Checking again here covers another writer filling the disk cache after
    # the caller's initial lookup, including the periodic artwork warmup.
    try:
        result = _cached_result(cache_key) or fetch()
    except BaseException as exc:
        pending.set_exception(exc)
        if background:
            with _FETCH_LOCK:
                _BACKGROUND_RETRY_AT[cache_key] = time.monotonic() + _REFRESH_RETRY_SECONDS
                _BACKGROUND_RETRY_AT.move_to_end(cache_key)
                if len(_BACKGROUND_RETRY_AT) > 128:
                    _BACKGROUND_RETRY_AT.popitem(last=False)
        raise
    else:
        pending.set_result(result)
        return result
    finally:
        with _FETCH_LOCK:
            _IN_FLIGHT.pop(cache_key, None)
            _BACKGROUND_KEYS.discard(cache_key)


def _refresh_cached_artwork(cache_key, pending, fetch):
    try:
        _complete_fetch(cache_key, pending, fetch, background=True)
    except ArtworkProxyError:
        pass  # The individual provider failures have already been logged.


def _get_or_fetch_artwork(cache_key, timeout, fetch):
    cached = _cached_result(cache_key, allow_stale=True)
    if cached and not cached["is_stale"]:
        return cached

    with _FETCH_LOCK:
        pending = _IN_FLIGHT.get(cache_key)
        if cached:
            retry_at = _BACKGROUND_RETRY_AT.get(cache_key, 0)
            if (
                pending is None
                and len(_BACKGROUND_KEYS) < _MAX_BACKGROUND_REFRESHES
                and time.monotonic() >= retry_at
            ):
                pending = Future()
                _IN_FLIGHT[cache_key] = pending
                _BACKGROUND_KEYS.add(cache_key)
                try:
                    _REFRESH_POOL.submit(_refresh_cached_artwork, cache_key, pending, fetch)
                except RuntimeError:  # Executor shutdown.
                    _IN_FLIGHT.pop(cache_key)
                    _BACKGROUND_KEYS.remove(cache_key)
            return cached
        owns_fetch = pending is None
        if owns_fetch:
            pending = Future()
            _IN_FLIGHT[cache_key] = pending

    try:
        if owns_fetch:
            return _complete_fetch(cache_key, pending, fetch)
        return pending.result(timeout=timeout)
    except (ArtworkProxyError, TimeoutError) as exc:
        fallback = _cached_result(cache_key, allow_stale=True)
        if fallback:
            return fallback
        if isinstance(exc, ArtworkProxyError):
            raise
        raise ArtworkProxyError(502, "Artwork fetch wait expired") from exc


def fetch_monitoring_avatar(server, avatar, external_user_id):
    """Fetch a stored provider avatar using a fixed origin or the configured Jellyfin server."""
    avatar = str(avatar or "").strip()
    provider = server["type"]
    headers = {}
    http = requests
    if provider == "plex":
        try:
            url = urlsplit(avatar)
        except ValueError:
            return None
        if url.scheme != "https" or url.netloc not in {
            "plex.tv", "www.plex.tv", "metadata-static.plex.tv", "images.plex.tv", "secure.gravatar.com",
        } or url.query or url.fragment:
            return None
        urls = [avatar]
    elif provider == "jellyfin" and re.fullmatch(r"[0-9a-fA-F-]{32,36}", str(external_user_id or "")):
        path = f"/Users/{external_user_id}/Images/Primary"
        if avatar.split("?", 1)[0].lower() != path.lower() or not server.get("token"):
            return None
        urls = [base + path for base in _server_bases(server)]
        headers = jellyfin_headers(server["token"])
        http = server_http_session(server)
    else:
        return None

    cache_key = artwork_cache_key("user-avatar", server["id"], avatar)
    cached = _cached_result(cache_key)
    if cached:
        return cached
    for url in urls:
        try:
            with http.get(url, headers=headers, timeout=(2, 3), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    continue
                content = bytearray()
                for chunk in response.iter_content(16384):
                    content.extend(chunk)
                    if len(content) > 1024 * 1024:
                        break
                if len(content) > 1024 * 1024:
                    continue
                content = bytes(content)
                mime = detect_image_content_type(content)
                if mime:
                    write_artwork_cache(cache_key, content, mime)
                    return {"kind": "content", "content": content, "content_type": mime}
        except requests.RequestException:
            continue
    return _cached_result(cache_key, allow_stale=True)


def fetch_monitoring_artwork(server: dict, query, timeout: int = 10) -> dict:
    provider = str(server.get("type") or "").strip().lower()
    token = str(server.get("token") or "").strip()
    bases = _server_bases(server)
    if provider not in {"plex", "jellyfin"} or not token:
        raise ArtworkProxyError(404, "Unsupported server or missing token")
    if not bases:
        raise ArtworkProxyError(502, "No configured server URL")
    if provider == "plex":
        path = str(query.get("path") or "").strip()
        if not _safe_relative_media_path(path):
            raise ArtworkProxyError(400, "Invalid Plex artwork path")
        cache_key = artwork_cache_key("plex", server["id"], path)
        fetch = partial(_fetch_artwork_candidates, server, provider, cache_key, bases,
                        _plex_candidate_paths(path), token, timeout)
        return _get_or_fetch_artwork(cache_key, timeout, fetch)

    item_id = str(query.get("item_id") or "").strip()
    if not item_id:
        raise ArtworkProxyError(400, "Missing Jellyfin item id")
    image_type = str(query.get("image_type") or "Primary").strip()
    image_index = query.get("image_index")
    width = str(query.get("w") or "120")
    quality = str(query.get("q") or "90")
    cache_key = artwork_cache_key("jellyfin", server["id"], item_id, image_type, image_index, width, quality)
    paths = [f"/Items/{item_id}/Images/{image_type}"]
    if image_index not in (None, ""):
        paths[0] += f"/{image_index}"
    if image_type.lower() != "primary":
        paths.append(f"/Items/{item_id}/Images/Primary")
    fetch = partial(
        _fetch_artwork_candidates,
        server, provider, cache_key, bases, paths, token, timeout,
        params={"maxWidth": width, "quality": quality},
    )
    return _get_or_fetch_artwork(cache_key, timeout, fetch)
