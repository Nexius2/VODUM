import json
import os
import random
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from core.plex_rate_limit import wait_for_plex_slot
import requests
from flask import current_app, request, session, url_for

from db_manager import DBManager
from logging_utils import get_logger


logger = get_logger("dashboard_quote_easter_egg")

CONFIG_FILE = "cinema_quotes.json"
CACHE_FILE = "dashboard_quote_easter_egg.json"


def _get_db():
    return DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))


def _get_appdata_dir():
    db_path = os.environ.get("DATABASE_PATH", "/appdata/database.db")
    return os.path.dirname(db_path) or "/appdata"


def _get_cache_path():
    cache_dir = os.path.join(_get_appdata_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, CACHE_FILE)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _get_quotes_path():
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "static" / "easter_eggs" / CONFIG_FILE,
        here.parent.parent.parent / "static" / "easter_eggs" / CONFIG_FILE,
    ]

    for path in candidates:
        if path.exists():
            return path

    return candidates[0]


def _load_quotes():
    path = _get_quotes_path()

    if not path.exists():
        logger.warning(f"Quotes file not found: {path}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logger.error(f"Quotes file root is not a list: {path}")
            return []

        logger.info(f"Loaded {len(data)} quote entries from {path}")
        return data

    except Exception:
        logger.exception(f"Failed to load quotes file: {path}")
        return []


def _load_cache():
    path = _get_cache_path()

    if not os.path.exists(path):
        logger.info(f"No dashboard quote cache file yet: {path}")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if not isinstance(payload, dict):
            logger.warning(f"Dashboard quote cache is not a dict: {path}")
            return None

        return payload

    except Exception:
        logger.exception(f"Failed to read dashboard quote cache: {path}")
        return None


def _save_cache(payload):
    path = _get_cache_path()

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved dashboard quote cache: {path}")

    except Exception:
        logger.exception(f"Failed to save dashboard quote cache: {path}")


def _quote_key(entry):
    key = _normalize_str((entry or {}).get("key"))
    if key:
        return key

    ids = (entry or {}).get("ids") or {}
    return _normalize_str(ids.get("imdb")) or _normalize_str(ids.get("tmdb"))


def _load_rotation(cached):
    rotation = (cached or {}).get("rotation") or {}
    if not isinstance(rotation, dict):
        return {"seen_keys": []}

    seen = rotation.get("seen_keys") or []
    if not isinstance(seen, list):
        seen = []

    cleaned = []
    for key in seen:
        key = _normalize_str(key)
        if key and key not in cleaned:
            cleaned.append(key)

    return {"seen_keys": cleaned}


def _with_rotation(payload, seen_keys):
    payload["rotation"] = {
        "seen_keys": list(seen_keys or []),
    }
    return payload


def _normalize_str(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _candidate_bases(server):
    bases = []

    for u in (server.get("url"), server.get("local_url"), server.get("public_url")):
        if not u:
            continue

        b = str(u).strip().rstrip("/")
        if not b:
            continue

        if not (b.startswith("http://") or b.startswith("https://")):
            continue

        if b not in bases:
            bases.append(b)

    return bases


def _get_servers():
    db = _get_db()

    rows = db.query(
        """
        SELECT id, name, type, url, local_url, public_url, token, status, cooldown_until
        FROM servers
        WHERE LOWER(type) IN ('plex', 'jellyfin')
          AND token IS NOT NULL
          AND TRIM(token) != ''
          AND COALESCE(status, '') != 'down'
          AND (
                cooldown_until IS NULL
                OR TRIM(cooldown_until) = ''
                OR cooldown_until <= CURRENT_TIMESTAMP
          )
        ORDER BY name
        """
    )

    servers = [dict(r) for r in rows]
    logger.info(f"Found {len(servers)} eligible online servers for dashboard quote refresh")
    return servers


def _quote_text_for_language(entry, language="en"):
    quotes = entry.get("quotes") or {}
    if not isinstance(quotes, dict):
        return None

    candidates = []
    lang = (language or "").strip().lower()
    if lang:
        candidates.append(lang)
        if "-" in lang:
            candidates.append(lang.split("-", 1)[0])
    candidates.extend(["en", "fr"])

    for code in candidates:
        text = quotes.get(code)
        if text is None:
            continue
        text = str(text).strip()
        if text:
            return text

    for text in quotes.values():
        text = str(text).strip()
        if text:
            return text

    return None


def _pick_quote_text(entry):
    return _quote_text_for_language(entry, "en")


def _match_plex_guids(guid_nodes, imdb, tmdb):
    imdb = _normalize_str(imdb)
    tmdb = _normalize_str(tmdb)

    found_imdb = None
    found_tmdb = None

    for g in guid_nodes:
        gid = str(g.attrib.get("id") or "").strip().lower()

        if not gid:
            continue

        if gid.startswith("imdb://"):
            found_imdb = gid.replace("imdb://", "", 1).strip()

        elif gid.startswith("tmdb://"):
            found_tmdb = gid.replace("tmdb://", "", 1).strip()

        elif "imdb.com/title/" in gid:
            found_imdb = gid.rsplit("/", 1)[-1].strip()

        elif "themoviedb.org/" in gid:
            found_tmdb = gid.rsplit("/", 1)[-1].strip()

    if imdb and found_imdb and found_imdb.lower() == imdb.lower():
        return True

    if tmdb and found_tmdb and found_tmdb == tmdb:
        return True

    return False


def _resolve_on_plex(server, media_type, imdb, tmdb):
    token = server.get("token")
    bases = _candidate_bases(server)

    if not token or not bases:
        return None

    plex_type = "1" if media_type == "movie" else "2"

    params = {
        "X-Plex-Token": token,
        "includeGuids": "1",
        "type": plex_type,
    }

    for base in bases:
        url = f"{base}/library/all"

        try:
            logger.info(f"[PLEX] Lookup on server={server.get('name')} url={url}")

            wait_for_plex_slot(base)
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()

            root = ET.fromstring(r.text)

            for node in root:
                if node.tag not in ("Video", "Directory"):
                    continue

                if not _match_plex_guids(node.findall("Guid"), imdb, tmdb):
                    continue

                poster_path = (
                    node.attrib.get("thumb")
                    or node.attrib.get("grandparentThumb")
                    or node.attrib.get("parentThumb")
                )
                backdrop_path = (
                    node.attrib.get("art")
                    or node.attrib.get("grandparentArt")
                    or node.attrib.get("parentArt")
                )

                if not poster_path:
                    logger.info(
                        f"[PLEX] Match found without poster on server={server.get('name')} title={node.attrib.get('title')}"
                    )
                    continue

                title = node.attrib.get("title") or "Unknown"
                year = node.attrib.get("year")

                logger.info(
                    f"[PLEX] Exact match found server={server.get('name')} title={title} year={year}"
                )

                return {
                    "provider": "plex",
                    "server_id": int(server["id"]),
                    "server_name": server.get("name"),
                    "title": title,
                    "year": year,
                    "poster_mode": "plex_path",
                    "poster_path": poster_path,
                    "poster_item_id": None,
                    "backdrop_mode": "plex_path",
                    "backdrop_path": backdrop_path,
                    "backdrop_item_id": None,
                }

        except Exception:
            logger.exception(
                f"[PLEX] Lookup failed on server={server.get('name')} url={url}"
            )

    return None


def _resolve_on_jellyfin(server, media_type, imdb, tmdb):
    token = server.get("token")
    bases = _candidate_bases(server)

    if not token or not bases:
        return None

    item_type = "Movie" if media_type == "movie" else "Series"
    headers = {
        "X-Emby-Token": token,
        "Accept": "application/json",
    }

    page_size = 200

    for base in bases:
        start_index = 0

        while True:
            url = f"{base}/Items"
            params = {
                "Recursive": "true",
                "IncludeItemTypes": item_type,
                "Fields": "ProviderIds,ProductionYear",
                "Limit": str(page_size),
                "StartIndex": str(start_index),
            }

            try:
                logger.info(
                    f"[JELLYFIN] Lookup on server={server.get('name')} url={url} start_index={start_index}"
                )

                r = requests.get(url, headers=headers, params=params, timeout=30)
                r.raise_for_status()

                data = r.json() or {}
                items = data.get("Items") or []

                if not items:
                    break

                for item in items:
                    provider_ids = item.get("ProviderIds") or {}
                    item_imdb = _normalize_str(provider_ids.get("Imdb"))
                    item_tmdb = _normalize_str(provider_ids.get("Tmdb"))

                    matched = False

                    if imdb and item_imdb and item_imdb.lower() == imdb.lower():
                        matched = True

                    if tmdb and item_tmdb and item_tmdb == tmdb:
                        matched = True

                    if not matched:
                        continue

                    item_id = item.get("Id")
                    if not item_id:
                        continue

                    title = item.get("Name") or "Unknown"
                    year = item.get("ProductionYear")

                    logger.info(
                        f"[JELLYFIN] Exact match found server={server.get('name')} title={title} year={year}"
                    )

                    return {
                        "provider": "jellyfin",
                        "server_id": int(server["id"]),
                        "server_name": server.get("name"),
                        "title": title,
                        "year": year,
                        "poster_mode": "jellyfin_item",
                        "poster_path": None,
                        "poster_item_id": str(item_id),
                        "backdrop_mode": "jellyfin_item",
                        "backdrop_path": None,
                        "backdrop_item_id": str(item_id),
                    }

                if len(items) < page_size:
                    break

                start_index += page_size

            except requests.RequestException as e:
                logger.warning(
                    f"[JELLYFIN] Lookup skipped on server={server.get('name')} "
                    f"url={url} start_index={start_index}: {e}"
                )
                break

            except Exception:
                logger.exception(
                    f"[JELLYFIN] Unexpected lookup error on server={server.get('name')} "
                    f"url={url} start_index={start_index}"
                )
                break

    return None


def _resolve_media(entry):
    media_type = str(entry.get("media_type") or "").strip().lower()
    if media_type == "tv":
        media_type = "show"
    if media_type not in {"movie", "show"}:
        logger.warning(f"Unsupported media_type for quote entry: {entry.get('key')}")
        return None

    ids = entry.get("ids") or {}
    imdb = _normalize_str(ids.get("imdb"))
    tmdb = _normalize_str(ids.get("tmdb"))

    if not imdb and not tmdb:
        logger.warning(f"Quote entry skipped (no imdb/tmdb): {entry.get('key')}")
        return None

    servers = _get_servers()
    random.shuffle(servers)

    for server in servers:
        stype = str(server.get("type") or "").strip().lower()

        if stype == "plex":
            resolved = _resolve_on_plex(server, media_type, imdb, tmdb)
            if resolved:
                return resolved

        elif stype == "jellyfin":
            resolved = _resolve_on_jellyfin(server, media_type, imdb, tmdb)
            if resolved:
                return resolved

    logger.info(f"No media match found for quote entry: {entry.get('key')}")
    return None


def refresh_dashboard_quote_cache(force=False):
    today = _today_str()
    cached = _load_cache()

    cache_is_legacy = False
    if cached and cached.get("day") == today and cached.get("none") is not True:
        has_new_poster_fields = (
            (cached.get("poster_mode") == "plex_path" and cached.get("server_id") and cached.get("poster_path"))
            or (cached.get("poster_mode") == "jellyfin_item" and cached.get("server_id") and cached.get("poster_item_id"))
        )
        has_legacy_poster_url = bool(cached.get("poster_url"))

        if not has_new_poster_fields and has_legacy_poster_url:
            cache_is_legacy = True
            logger.warning("Dashboard quote cache is legacy for today -> forcing rebuild")

    if not force and cached and cached.get("day") == today and not cache_is_legacy:
        logger.info(f"Dashboard quote cache already ready for today ({today})")
        return cached

    quotes = _load_quotes()
    if not quotes:
        payload = {
            "day": today,
            "none": True,
            "reason": "quotes_file_empty_or_missing",
        }
        _with_rotation(payload, (_load_rotation(cached).get("seen_keys") or []))
        _save_cache(payload)
        return payload

    candidates = []
    for entry in quotes:
        quote_text = _pick_quote_text(entry)
        if not quote_text:
            continue
        candidates.append(entry)

    if not candidates:
        payload = {
            "day": today,
            "none": True,
            "reason": "no_english_quotes_available",
        }
        _with_rotation(payload, (_load_rotation(cached).get("seen_keys") or []))
        _save_cache(payload)
        return payload

    rotation = _load_rotation(cached)
    seen_keys = rotation.get("seen_keys") or []
    seen_set = set(seen_keys)

    unseen_candidates = [entry for entry in candidates if _quote_key(entry) not in seen_set]
    random.shuffle(unseen_candidates)

    retry_candidates = list(candidates)
    random.shuffle(retry_candidates)

    passes = [
        (unseen_candidates, False),
        (retry_candidates, True),
    ]

    for pass_candidates, reset_rotation in passes:
        if not pass_candidates:
            continue

        for entry in pass_candidates:
            quote_text = _pick_quote_text(entry)
            resolved = _resolve_media(entry)

            if not quote_text or not resolved:
                continue

            key = _quote_key(entry) or entry.get("key")
            next_seen = [] if reset_rotation else list(seen_keys)
            if key and key not in next_seen:
                next_seen.append(key)

            payload = {
                "day": today,
                "none": False,
                "quote_key": entry.get("key"),
                "phrase": quote_text,
                "title": resolved.get("title"),
                "year": resolved.get("year"),
                "provider": resolved.get("provider"),
                "server_id": resolved.get("server_id"),
                "server_name": resolved.get("server_name"),
                "poster_mode": resolved.get("poster_mode"),
                "poster_path": resolved.get("poster_path"),
                "poster_item_id": resolved.get("poster_item_id"),
                "backdrop_mode": resolved.get("backdrop_mode"),
                "backdrop_path": resolved.get("backdrop_path"),
                "backdrop_item_id": resolved.get("backdrop_item_id"),
            }
            _with_rotation(payload, next_seen)

            _save_cache(payload)

            logger.info(
                f"Dashboard quote selected key={payload.get('quote_key')} provider={payload.get('provider')} server={payload.get('server_name')} title={payload.get('title')} year={payload.get('year')} rotation_reset={reset_rotation}"
            )
            return payload

    payload = {
        "day": today,
        "none": True,
        "reason": "no_matching_media_found",
    }
    _with_rotation(payload, seen_keys)
    _save_cache(payload)
    logger.info("No valid dashboard quote found for today")
    return payload



def _active_quote_language():
    try:
        lang = session.get("lang")
        if lang:
            return str(lang)
    except Exception:
        pass

    try:
        best = request.accept_languages.best_match(["fr", "en", "de", "es", "it"])
        if best:
            return str(best)
    except Exception:
        pass

    return "en"


def _build_local_quote_fallback():
    quotes = _load_quotes()
    language = _active_quote_language()

    candidates = []
    for entry in quotes:
        phrase = _quote_text_for_language(entry, language)
        if phrase:
            candidates.append((entry, phrase))

    if not candidates:
        return None

    rnd = random.Random(_today_str())
    entry, phrase = candidates[rnd.randrange(len(candidates))]

    return {
        "phrase": phrase,
        "poster_url": None,
        "title": None,
        "year": None,
        "fallback": True,
        "quote_key": entry.get("key"),
    }


def _quote_image_url(server_id, mode, path=None, item_id=None, image_type="Primary", width=None):
    if not server_id:
        return None

    try:
        if mode == "plex_path" and path:
            return url_for(
                "api_monitoring_poster",
                server_id=int(server_id),
                path=path,
            )

        if mode == "jellyfin_item" and item_id:
            kwargs = {
                "server_id": int(server_id),
                "item_id": str(item_id),
                "image_type": image_type,
            }
            if width:
                kwargs["w"] = str(width)
            return url_for("api_monitoring_poster", **kwargs)
    except Exception:
        logger.exception("Failed to build quote artwork url")

    return None


def _build_quote_artwork_urls(payload):
    payload = payload or {}
    server_id = payload.get("server_id")

    poster_url = _quote_image_url(
        server_id,
        payload.get("poster_mode"),
        path=payload.get("poster_path"),
        item_id=payload.get("poster_item_id"),
        image_type="Primary",
        width=420,
    )

    backdrop_url = _quote_image_url(
        server_id,
        payload.get("backdrop_mode"),
        path=payload.get("backdrop_path"),
        item_id=payload.get("backdrop_item_id"),
        image_type="Backdrop",
        width=1400,
    )

    if not poster_url and payload.get("poster_url"):
        poster_url = payload.get("poster_url")

    return poster_url, backdrop_url


def build_login_quote_artwork_request(kind="poster"):
    payload = _load_cache()
    if not payload or payload.get("day") != _today_str() or payload.get("none") is True:
        return None

    kind = str(kind or "poster").strip().lower()
    if kind == "backdrop":
        mode = payload.get("backdrop_mode") or payload.get("poster_mode")
        path = payload.get("backdrop_path") or payload.get("poster_path")
        item_id = payload.get("backdrop_item_id") or payload.get("poster_item_id")
        image_type = "Backdrop" if payload.get("backdrop_mode") else "Primary"
        width = "1400" if image_type == "Backdrop" else "420"
    else:
        mode = payload.get("poster_mode")
        path = payload.get("poster_path")
        item_id = payload.get("poster_item_id")
        image_type = "Primary"
        width = "420"

    server_id = payload.get("server_id")
    if not server_id or not mode:
        return None

    if mode == "plex_path" and path:
        return {"server_id": int(server_id), "query": {"path": path}}

    if mode == "jellyfin_item" and item_id:
        return {
            "server_id": int(server_id),
            "query": {
                "item_id": str(item_id),
                "image_type": image_type,
                "w": width,
            },
        }

    return None


def build_dashboard_quote_card():
    payload = _load_cache()
    if not payload:
        logger.info("Dashboard quote cache missing -> using local quote fallback")
        return _build_local_quote_fallback()

    if payload.get("day") != _today_str():
        logger.info("Dashboard quote cache is outdated -> using local quote fallback")
        return _build_local_quote_fallback()

    if payload.get("none") is True:
        logger.info("Dashboard quote cache says no matching media for today -> using local quote fallback")
        return _build_local_quote_fallback()

    poster_url, backdrop_url = _build_quote_artwork_urls(payload)

    if not poster_url:
        logger.warning("Dashboard quote cache exists but poster_url could not be built -> using local quote fallback")
        return _build_local_quote_fallback()

    return {
        "phrase": payload.get("phrase"),
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
        "title": payload.get("title"),
        "year": payload.get("year"),
        "quote_key": payload.get("quote_key"),
    }


def build_login_quote_visual():
    payload = _load_cache()
    if not payload or payload.get("day") != _today_str() or payload.get("none") is True:
        return None

    has_poster = build_login_quote_artwork_request("poster") is not None
    has_backdrop = build_login_quote_artwork_request("backdrop") is not None
    if not has_poster and not has_backdrop:
        return None

    return {
        "phrase": payload.get("phrase"),
        "poster_url": url_for("login_quote_artwork", kind="poster") if has_poster else (url_for("login_quote_artwork", kind="backdrop") if has_backdrop else None),
        "backdrop_url": url_for("login_quote_artwork", kind="backdrop") if has_backdrop else (url_for("login_quote_artwork", kind="poster") if has_poster else None),
        "title": payload.get("title"),
        "year": payload.get("year"),
    }
