from __future__ import annotations

from core.providers.plex import PlexProvider
from core.providers.jellyfin import JellyfinProvider

def get_provider(server: dict):
    t = (server.get("type") or "").lower()
    if t == "plex":
        return PlexProvider(server)
    if t == "jellyfin":
        return JellyfinProvider(server)
    raise ValueError(f"Unsupported provider type: {server.get('type')}")
