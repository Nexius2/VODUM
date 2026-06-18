"""Fetch monitoring artwork from configured media servers with disk-cache fallback."""

from __future__ import annotations

import re

from core.http_security import server_http_session
from core.monitoring.artwork_cache import artwork_cache_key, read_artwork_cache, write_artwork_cache
from core.plex_rate_limit import wait_for_plex_slot


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


def fetch_monitoring_artwork(server: dict, query, timeout: int = 10) -> dict:
    provider = str(server.get("type") or "").strip().lower()
    token = str(server.get("token") or "").strip()
    bases = _server_bases(server)
    if provider not in {"plex", "jellyfin"} or not token:
        raise ArtworkProxyError(404, "Unsupported server or missing token")
    if not bases:
        raise ArtworkProxyError(502, "No configured server URL")
    http = server_http_session(server)

    if provider == "plex":
        path = str(query.get("path") or "").strip()
        if not _safe_relative_media_path(path):
            raise ArtworkProxyError(400, "Invalid Plex artwork path")
        cache_key = artwork_cache_key("plex", server["id"], path)
        cached = _cached_result(cache_key)
        if cached:
            return cached
        for candidate_path in _plex_candidate_paths(path):
            for base in bases:
                try:
                    wait_for_plex_slot(base)
                    response = http.get(base + candidate_path, headers={"X-Plex-Token": token}, timeout=timeout)
                    response.raise_for_status()
                    return _content_result(cache_key, response)
                except Exception:
                    continue
        stale = _cached_result(cache_key, allow_stale=True)
        if stale:
            return stale
        raise ArtworkProxyError(502, "Plex artwork unavailable")

    item_id = str(query.get("item_id") or "").strip()
    if not item_id:
        raise ArtworkProxyError(400, "Missing Jellyfin item id")
    image_type = str(query.get("image_type") or "Primary").strip()
    image_index = query.get("image_index")
    width = str(query.get("w") or "120")
    quality = str(query.get("q") or "90")
    cache_key = artwork_cache_key("jellyfin", server["id"], item_id, image_type, image_index, width, quality)
    cached = _cached_result(cache_key)
    if cached:
        return cached
    paths = [f"/Items/{item_id}/Images/{image_type}"]
    if image_index not in (None, ""):
        paths[0] += f"/{image_index}"
    if image_type.lower() != "primary":
        paths.append(f"/Items/{item_id}/Images/Primary")
    for path in paths:
        for base in bases:
            try:
                response = http.get(
                    base + path,
                    headers={"X-Emby-Token": token},
                    params={"maxWidth": width, "quality": quality},
                    timeout=timeout,
                )
                response.raise_for_status()
                return _content_result(cache_key, response)
            except Exception:
                continue
    stale = _cached_result(cache_key, allow_stale=True)
    if stale:
        return stale
    raise ArtworkProxyError(502, "Jellyfin artwork unavailable")
