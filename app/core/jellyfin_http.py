from typing import Any, List
from urllib.parse import urlsplit, urlunsplit


def _build_api_url(base_url: str, path: str, token: str) -> str:
    base_url = (base_url or "").rstrip("/")
    path = "/" + (path or "").lstrip("/")
    parts = urlsplit(f"{base_url}{path}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _get_json(session: Any, url: str, timeout: int = 20, token: str | None = None) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Emby-Token"] = token
    response = session.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _jellyfin_pick_user_id(session: Any, base_url: str, token: str, timeout: int = 20) -> str | None:
    users_url = _build_api_url(base_url, "/Users", token)
    users = _get_json(session, users_url, timeout=timeout, token=token) or []
    if not isinstance(users, list) or not users:
        return None

    # Essaye de prendre un admin si possible, sinon le premier
    for u in users:
        if isinstance(u, dict) and (u.get("Policy") or {}).get("IsAdministrator"):
            if u.get("Id"):
                return str(u["Id"])

    u0 = users[0]
    if isinstance(u0, dict) and u0.get("Id"):
        return str(u0["Id"])
    return None

def _jellyfin_list_user_ids(session: Any, base_url: str, token: str, timeout: int = 20) -> List[str]:
    """
    Retourne une liste de UserId Jellyfin (admin d’abord si possible, puis les autres).
    Utile pour fallback item_count quand le no-user renvoie 0/None.
    """
    users_url = _build_api_url(base_url, "/Users", token)
    users = _get_json(session, users_url, timeout=timeout, token=token) or []
    if not isinstance(users, list):
        return []

    admins = []
    others = []
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = u.get("Id")
        if not uid:
            continue
        uid = str(uid)
        is_admin = bool((u.get("Policy") or {}).get("IsAdministrator"))
        (admins if is_admin else others).append(uid)

    return admins + others


def _jellyfin_library_total_items(
    session: Any,
    base_url: str,
    token: str,
    library_item_id: str,
    *,
    user_id: str,
    timeout: int = 20,
) -> int | None:
    # Limit=1 (pas 0) + EnableTotalRecordCount=true
    url = (
        f"{base_url.rstrip('/')}/Users/{user_id}/Items"
        f"?ParentId={library_item_id}&Recursive=true&StartIndex=0&Limit=1&EnableTotalRecordCount=true"
    )
    r = session.get(url, headers={"X-Emby-Token": token, "Accept": "application/json"}, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    trc = data.get("TotalRecordCount")
    if trc is None:
        return None
    try:
        return int(trc)
    except Exception:
        return None

def _jellyfin_library_total_items_no_user(
    session: Any,
    base_url: str,
    token: str,
    library_item_id: str,
    timeout: int = 20,
) -> int | None:
    headers = {"X-Emby-Token": token, "Accept": "application/json"}

    # Tentative 1: /Items/Counts?ParentId=...
    url = _build_api_url(
        base_url,
        f"/Items/Counts?ParentId={library_item_id}&Recursive=true",
        token,
    )
    r = session.get(url, headers=headers, timeout=timeout)
    if r.status_code == 200:
        try:
            data = r.json()
            # selon versions : ItemCount / Items / TotalCount...
            for key in ("ItemCount", "Items", "TotalCount", "Count"):
                if key in data and data[key] is not None:
                    return int(data[key])

            # fallback Jellyfin courant: MovieCount/SeriesCount/EpisodeCount...
            summed = 0
            any_found = False
            for k, v in data.items():
                if k.endswith("Count"):
                    try:
                        summed += int(v)
                        any_found = True
                    except Exception:
                        pass
            if any_found:
                return summed

        except Exception:
            pass

    # Tentative 2 (fallback): /Items?...EnableTotalRecordCount=true
    url = _build_api_url(
        base_url,
        f"/Items?ParentId={library_item_id}&Recursive=true&StartIndex=0&Limit=1&EnableTotalRecordCount=true",
        token,
    )
    r = session.get(url, headers=headers, timeout=timeout)
    if r.status_code != 200:
        return None

    try:
        data = r.json()
        trc = data.get("TotalRecordCount")
        if trc is None:
            return None
        return int(trc)
    except Exception:
        return None
