from __future__ import annotations

from core.providers.plex import PlexProvider
from core.providers.jellyfin import JellyfinProvider
from core.providers.base import ServerConfig


def _coerce_server(server):
    # Déjà au bon format
    if isinstance(server, ServerConfig):
        return server

    # Cas courant: dict venant de la DB (stream_enforcer, etc.)
    if isinstance(server, dict):
        return ServerConfig(
            id=int(server.get("id") or 0),
            type=str(server.get("type") or ""),
            url=server.get("url"),
            local_url=server.get("local_url"),
            public_url=server.get("public_url"),
            token=server.get("token"),
            server_identifier=str(server.get("server_identifier") or ""),
            settings_json=server.get("settings_json"),
        )

    # Fallback: objet “attr-access”
    return server


def get_provider(server):
    srv = _coerce_server(server)
    t = (getattr(srv, "type", None) or "").lower()

    if t == "plex":
        return PlexProvider(srv, timeout=8)
    if t == "jellyfin":
        return JellyfinProvider(srv, timeout=15)

    raise ValueError(f"Unsupported provider type: {t}")
