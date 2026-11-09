"""Presentation definitions only; each model reserves its own future engine key."""

COLLECTION_MODELS = (
    {"id":"hidden_gems", "glyph":"◇", "theme":"spotlight", "media_types":["movie","shows"], "default_limit":30, "default_sort":"rank", "daily":False, "secondary":True},
    {"id": "memoria", "glyph": "✦", "theme": "memoria", "media_types": ["movie", "shows"], "default_limit": 30, "default_sort": "release", "daily": False},
    {"id": "streaming_country", "glyph": "↗", "theme": "country", "media_types": ["movie", "shows"], "default_limit": 0, "default_sort": "rank", "daily": False},
    {"id": "streaming_worldwide", "glyph": "◎", "theme": "world", "media_types": ["movie", "shows"], "default_limit": 20, "default_sort": "rank", "daily": False},
    {"id": "seasonal", "glyph": "◈", "theme": "seasonal", "media_types": ["movie"], "default_limit": 30, "default_sort": "daily_random", "daily": False},
    {"id": "recent_releases", "glyph": "◷", "theme": "releases", "media_types": ["movie", "shows"], "default_limit": 0, "default_sort": "release", "daily": False},
    {"id": "spotlight", "glyph": "ϟ", "theme": "spotlight", "media_types": ["movie"], "default_limit": 0, "default_sort": "availability", "daily": False},
    {"id":"imdb", "glyph":"★", "theme":"spotlight", "media_types":["movie","shows"], "default_limit":0, "default_sort":"rank", "daily":False, "secondary":True},
    {"id":"recently_added", "glyph":"+", "theme":"releases", "media_types":["movie","shows"], "default_limit":30, "default_sort":"added", "daily":False, "secondary":True},
    {"id":"kids", "glyph":"☀", "theme":"releases", "media_types":["movie","shows"], "default_limit":30, "default_sort":"rank", "daily":False, "secondary":True},
    {"id":"tmdb", "glyph":"★", "theme":"spotlight", "media_types":["movie","shows"], "default_limit":250, "default_sort":"rank", "daily":False, "secondary":True},
    {"id":"family", "glyph":"⌂", "theme":"releases", "media_types":["movie","shows"], "default_limit":30, "default_sort":"rank", "daily":False, "secondary":True},
    {"id":"awards", "glyph":"♛", "theme":"spotlight", "media_types":["movie","shows"], "default_limit":30, "default_sort":"rank", "daily":False, "secondary":True},
    {"id":"top_country", "glyph":"⚑", "theme":"country", "media_types":["movie","shows"], "default_limit":30, "default_sort":"rank", "daily":False, "secondary":True},
    {"id":"franchises", "glyph":"◫", "theme":"spotlight", "media_types":["movie"], "default_limit":0, "default_sort":"release", "daily":False, "secondary":True},
    {"id":"continents", "glyph":"◍", "theme":"world", "media_types":["movie","shows"], "default_limit":0, "default_sort":"added", "daily":False, "secondary":True},
    {"id":"platforms", "glyph":"▶", "theme":"world", "media_types":["movie","shows"], "default_limit":0, "default_sort":"added", "daily":False, "secondary":True},
)

FUTURE_MODELS = (
    "imdb", "tmdb", "recently_added", "kids", "family", "awards", "top_country", "franchises",
    "platforms", "continents", "hidden_gems",
)


def collection_catalog():
    return [{**model, "engine_key": model["id"], "engine_available":model['id'] in ('memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems')} for model in COLLECTION_MODELS]
