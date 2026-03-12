import json
import os
import random
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
from flask import current_app, url_for

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


def _load_quotes():
    path = Path(__file__).resolve().parent.parent / "static" / "easter_eggs" / CONFIG_FILE

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
        SELECT id, name, type, url, local_url, public_url, token
        FROM servers
        WHERE LOWER(type) IN ('plex', 'jellyfin')
          AND token IS NOT NULL
          AND TRIM(token) != ''
        ORDER BY name
        """
    )

    servers = [dict(r) for r in rows]
    logger.info(f"Found {len(servers)} eligible servers for dashboard quote refresh")
    return servers


def _pick_quote_text(entry):
    quotes = entry.get("quotes") or {}
    if not isinstance(quotes, dict):
        return None

    text = quotes.get("en")
    if text is None:
        return None

    text = str(text).strip()
    return text or None


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
                    }

                if len(items) < page_size:
                    break

                start_index += page_size

            except Exception:
                logger.exception(
                    f"[JELLYFIN] Lookup failed on server={server.get('name')} url={url} start_index={start_index}"
                )
                break

    return None


def _resolve_media(entry):
    media_type = str(entry.get("media_type") or "").strip().lower()
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
        _save_cache(payload)
        return payload

    random.shuffle(candidates)

    for entry in candidates:
        quote_text = _pick_quote_text(entry)
        resolved = _resolve_media(entry)

        if not quote_text or not resolved:
            continue

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
        }

        _save_cache(payload)

        logger.info(
            f"Dashboard quote selected key={payload.get('quote_key')} provider={payload.get('provider')} server={payload.get('server_name')} title={payload.get('title')} year={payload.get('year')}"
        )
        return payload

    payload = {
        "day": today,
        "none": True,
        "reason": "no_matching_media_found",
    }
    _save_cache(payload)
    logger.info("No valid dashboard quote found for today")
    return payload


def build_dashboard_quote_card():
    payload = _load_cache()
    if not payload:
        logger.info("Dashboard quote cache missing -> returning None (no request-time lookup)")
        return None

    if payload.get("day") != _today_str():
        logger.info("Dashboard quote cache is outdated -> returning None (no request-time lookup)")
        return None

    if payload.get("none") is True:
        logger.info("Dashboard quote cache says no valid entry for today")
        return None

    server_id = payload.get("server_id")
    poster_mode = payload.get("poster_mode")
    poster_path = payload.get("poster_path")
    poster_item_id = payload.get("poster_item_id")

    poster_url = None

    try:
        if poster_mode == "plex_path" and server_id and poster_path:
            poster_url = url_for(
                "api_monitoring_poster",
                server_id=int(server_id),
                path=poster_path,
            )
        elif poster_mode == "jellyfin_item" and server_id and poster_item_id:
            poster_url = url_for(
                "api_monitoring_poster",
                server_id=int(server_id),
                item_id=str(poster_item_id),
            )
        elif payload.get("poster_url"):
            # Compat cache legacy déjà stocké avec poster_url complet
            poster_url = payload.get("poster_url")
    except Exception:
        logger.exception("Failed to build poster_url from dashboard quote cache")
        poster_url = None

    if not poster_url:
        logger.warning("Dashboard quote cache exists but poster_url could not be built")
        return None

    return {
        "phrase": payload.get("phrase"),
        "poster_url": poster_url,
        "title": payload.get("title"),
        "year": payload.get("year"),
    }