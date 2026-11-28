"""Normalize external identifiers from modern and legacy Plex agents."""

_AGENT_PROVIDERS = {
    "com.plexapp.agents.imdb": "imdb",
    "com.plexapp.agents.themoviedb": "tmdb",
    "com.plexapp.agents.thetvdb": "tvdb",
}


def plex_external_guid(raw):
    scheme, separator, value = raw.partition("://")
    if not separator:
        return None
    provider = _AGENT_PROVIDERS.get(scheme.lower(), scheme.lower())
    value = value.split("?", 1)[0].strip("/")
    if provider in ("tmdb", "tvdb"):
        if not value.isascii() or not value.isdigit():
            return None
        value = value.lstrip("0")
    if provider in ("tmdb", "tvdb", "imdb") and value:
        return provider, value
    return None
