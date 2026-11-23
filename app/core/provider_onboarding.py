from __future__ import annotations


_DOWNLOAD_URLS = {
    "plex": "https://www.plex.tv/media-server-downloads/#plex-app",
    "jellyfin": "https://jellyfin.org/downloads/clients/",
}
_HELP_URLS = {
    "plex": "https://support.plex.tv/articles/categories/player-apps-platforms/",
    "jellyfin": "https://jellyfin.org/docs/general/clients/",
}


def provider_onboarding_links(provider: str) -> dict:
    normalized = str(provider or "").strip().lower()
    return {
        "provider_name": normalized.capitalize() if normalized in _DOWNLOAD_URLS else "",
        "player_download_url": _DOWNLOAD_URLS.get(normalized, ""),
        "player_help_url": _HELP_URLS.get(normalized, ""),
    }
