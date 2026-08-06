from typing import Any
from urllib.parse import urlsplit, urlunsplit


def build_jellyfin_api_url(base_url: str, path: str) -> str:
    raw = f"{(base_url or '').rstrip('/')}/{'%s' % (path or '').lstrip('/')}"
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def get_jellyfin_json(session, url: str, timeout: int = 20, token: str | None = None) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Emby-Token"] = token
    response = session.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def load_jellyfin_servers(db):
    return db.query(
        """
        SELECT id, name, url, local_url, public_url, token, status, cooldown_until
        FROM servers
        WHERE type = 'jellyfin'
        """
    )


def pick_jellyfin_base_url(server) -> str:
    return (
        (server.get("url") or "")
        or (server.get("local_url") or "")
        or (server.get("public_url") or "")
    ).strip().rstrip("/")
