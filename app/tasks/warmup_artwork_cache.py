#!/usr/bin/env python3
"""
warmup_artwork_cache.py
- Précharge le cache disque des posters/backdrops monitoring.
- Couvre les sessions live/récentes ET les cartes Top by library.
- Utilise le même resolver artwork que l'interface pour éviter de précharger des références obsolètes.
"""

import os
import time

import requests

from core.monitoring.artwork import _resolve_row_artwork
from core.plex_rate_limit import wait_for_plex_slot
from core.http_security import server_http_session
from logging_utils import get_logger, is_debug_mode_enabled
from routes.monitoring_api import (
    ARTWORK_DISK_CACHE_TTL_SECONDS,
    _artwork_cache_key,
    _artwork_cache_paths,
    _write_artwork_cache,
)
from tasks_engine import task_logs

log = get_logger("warmup_artwork_cache")

WARMUP_RECENT_LIMIT = int(os.environ.get("VODUM_ARTWORK_WARMUP_RECENT_LIMIT", "200"))
WARMUP_LIBRARY_TOP_PER_LIBRARY = int(os.environ.get("VODUM_ARTWORK_WARMUP_LIBRARY_TOP_PER_LIBRARY", "6"))
REQUEST_TIMEOUT = int(os.environ.get("VODUM_ARTWORK_WARMUP_TIMEOUT", "10"))


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _row_to_dict(row):
    try:
        return dict(row or {})
    except Exception:
        return row or {}


def _is_cache_fresh(cache_key: str) -> bool:
    img_path, meta_path = _artwork_cache_paths(cache_key)
    if not img_path or not meta_path:
        return False
    if not os.path.exists(img_path) or not os.path.exists(meta_path):
        return False
    age = time.time() - os.path.getmtime(img_path)
    return age <= ARTWORK_DISK_CACHE_TTL_SECONDS


def _server_bases(server):
    bases = []
    for key in ("url", "local_url", "public_url"):
        value = (server.get(key) or "").strip()
        if value:
            value = value.rstrip("/")
            if value not in bases:
                bases.append(value)
    return bases


def _fetch_plex(server, ref):
    path = (ref.get("path") or "").strip()
    token = server.get("token")
    if not path or not token:
        return None

    headers = {"X-Plex-Token": token}
    http = server_http_session(server)

    candidate_paths = [path]
    if path.endswith("/art"):
        candidate_paths.append(path[:-4] + "/thumb")

    last_error = None
    for candidate_path in dict.fromkeys(candidate_paths):
        for base in _server_bases(server):
            try:
                wait_for_plex_slot(base)
                response = http.get(base + candidate_path, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.content, response.headers.get("Content-Type") or "image/jpeg"
            except Exception as e:
                last_error = e
                continue

    if is_debug_mode_enabled() and last_error:
        log.debug(f"Plex artwork warmup failed for server={server.get('id')} path={path}: {last_error}")
    return None


def _fetch_jellyfin(server, ref):
    item_id = ref.get("item_id")
    if not item_id or not server.get("token"):
        return None

    image_type = (ref.get("image_type") or "Primary").strip()
    image_index = ref.get("image_index")
    width = str(ref.get("w") or "120")
    quality = str(ref.get("q") or "90")

    path = f"/Items/{item_id}/Images/{image_type}"
    if image_index not in (None, ""):
        path += f"/{image_index}"

    headers = {"X-Emby-Token": server.get("token")}
    params = {"maxWidth": width, "quality": quality}
    http = server_http_session(server)

    last_error = None
    for base in _server_bases(server):
        try:
            response = http.get(base + path, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.content, response.headers.get("Content-Type") or "image/jpeg"
        except Exception as e:
            last_error = e
            continue

    if image_type.lower() != "primary":
        fallback_path = f"/Items/{item_id}/Images/Primary"
        for base in _server_bases(server):
            try:
                response = http.get(base + fallback_path, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.content, response.headers.get("Content-Type") or "image/jpeg"
            except Exception as e:
                last_error = e
                continue

    if is_debug_mode_enabled() and last_error:
        log.debug(f"Jellyfin artwork warmup failed for server={server.get('id')} item_id={item_id}: {last_error}")
    return None


def _cache_key_for_ref(server_id, ref):
    ref = ref or {}
    provider = (ref.get("provider") or "").strip().lower()

    if provider == "plex":
        path = (ref.get("path") or "").strip()
        if not path:
            return None
        return _artwork_cache_key("plex", server_id, path)

    if provider == "jellyfin":
        item_id = ref.get("item_id")
        if not item_id:
            return None
        image_type = (ref.get("image_type") or "Primary").strip()
        image_index = ref.get("image_index")
        width = str(ref.get("w") or "120")
        quality = str(ref.get("q") or "90")
        return _artwork_cache_key("jellyfin", server_id, item_id, image_type, image_index, width, quality)

    return None


def _load_servers(db):
    rows = db.query(
        """
        SELECT id, LOWER(TRIM(type)) AS type, url, local_url, public_url, token, settings_json
        FROM servers
        WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')
          AND token IS NOT NULL
          AND TRIM(token) != ''
        """
    )
    return {int(row["id"]): _row_to_dict(row) for row in rows}


def _dedupe_candidates(rows):
    out = []
    seen = set()
    for row in rows or []:
        row = _row_to_dict(row)
        key = (
            row.get("source_table"),
            row.get("id"),
            row.get("server_id"),
            row.get("media_key"),
            row.get("media_type"),
            row.get("title"),
            row.get("grandparent_title"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _query_candidates(db, sql, params=()):
    try:
        return [_row_to_dict(r) for r in (db.query(sql, params) or [])]
    except Exception as e:
        log.warning(f"Unable to load artwork warmup candidates: {e}", exc_info=is_debug_mode_enabled())
        return []


def _load_candidates(db):
    recent_limit = max(1, _safe_int(WARMUP_RECENT_LIMIT, 200))
    top_per_library = max(1, _safe_int(WARMUP_LIBRARY_TOP_PER_LIBRARY, 6))

    live_rows = _query_candidates(
        db,
        """
        SELECT
          'media_sessions' AS source_table,
          id,
          server_id,
          provider,
          media_key,
          media_type,
          title,
          grandparent_title,
          raw_json,
          poster_ref_json,
          backdrop_ref_json,
          last_seen_at AS sort_date
        FROM media_sessions
        WHERE raw_json IS NOT NULL
           OR poster_ref_json IS NOT NULL
           OR backdrop_ref_json IS NOT NULL
        ORDER BY datetime(last_seen_at) DESC
        LIMIT ?
        """,
        (recent_limit,),
    )

    recent_history_rows = _query_candidates(
        db,
        """
        SELECT
          'media_session_history' AS source_table,
          id,
          server_id,
          provider,
          media_key,
          media_type,
          title,
          grandparent_title,
          raw_json,
          poster_ref_json,
          backdrop_ref_json,
          stopped_at AS sort_date
        FROM media_session_history
        WHERE raw_json IS NOT NULL
           OR poster_ref_json IS NOT NULL
           OR backdrop_ref_json IS NOT NULL
        ORDER BY datetime(stopped_at) DESC
        LIMIT ?
        """,
        (recent_limit,),
    )

    # Cible directement ce que l'onglet Monitoring > Libraries affiche :
    # les contenus les plus joués par bibliothèque sur la plage par défaut (30 jours).
    library_top_rows = _query_candidates(
        db,
        """
        WITH hist AS (
          SELECT
            h.id,
            h.server_id,
            h.provider,
            h.media_key,
            h.media_type,
            h.title,
            h.grandparent_title,
            h.raw_json,
            h.poster_ref_json,
            h.backdrop_ref_json,
            h.stopped_at,
            l.id AS library_id,
            CASE
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|series:' || LOWER(TRIM(h.grandparent_title))
              WHEN NULLIF(TRIM(h.media_key), '') IS NOT NULL
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|media:' || TRIM(h.media_key)
              ELSE 'server:' || CAST(h.server_id AS TEXT) || '|title:' || LOWER(TRIM(COALESCE(h.title, 'Unknown')))
            END AS media_group_key
          FROM media_session_history h
          JOIN libraries l
            ON l.server_id = h.server_id
           AND CAST(l.section_id AS TEXT) = CAST(h.library_section_id AS TEXT)
          WHERE h.stopped_at >= datetime('now', '-30 days')
            AND COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
            AND (h.raw_json IS NOT NULL OR h.poster_ref_json IS NOT NULL OR h.backdrop_ref_json IS NOT NULL)
        ),
        media_agg AS (
          SELECT
            library_id,
            media_group_key,
            COUNT(*) AS plays,
            MAX(stopped_at) AS last_play_at
          FROM hist
          GROUP BY library_id, media_group_key
        ),
        latest_snapshot AS (
          SELECT
            h.*,
            ROW_NUMBER() OVER (
              PARTITION BY h.library_id, h.media_group_key
              ORDER BY datetime(h.stopped_at) DESC, h.id DESC
            ) AS snapshot_rank
          FROM hist h
        ),
        ranked AS (
          SELECT
            ls.*,
            ma.plays,
            ROW_NUMBER() OVER (
              PARTITION BY ls.library_id
              ORDER BY ma.plays DESC, ma.last_play_at DESC, COALESCE(ls.title, ls.grandparent_title, '') COLLATE NOCASE ASC
            ) AS row_in_library
          FROM latest_snapshot ls
          JOIN media_agg ma
            ON ma.library_id = ls.library_id
           AND ma.media_group_key = ls.media_group_key
          WHERE ls.snapshot_rank = 1
        )
        SELECT
          'media_session_history' AS source_table,
          id,
          server_id,
          provider,
          media_key,
          media_type,
          title,
          grandparent_title,
          raw_json,
          poster_ref_json,
          backdrop_ref_json,
          stopped_at AS sort_date
        FROM ranked
        WHERE row_in_library <= ?
        ORDER BY library_id ASC, row_in_library ASC
        """,
        (top_per_library,),
    )

    return _dedupe_candidates(live_rows + library_top_rows + recent_history_rows)


def _resolve_refs(db, row):
    table_name = row.get("source_table")
    if table_name not in ("media_sessions", "media_session_history"):
        table_name = None

    try:
        return _resolve_row_artwork(row, db=db, table_name=table_name)
    except Exception as e:
        log.warning(
            f"Unable to resolve artwork refs for warmup row source={table_name} id={row.get('id')}: {e}",
            exc_info=is_debug_mode_enabled(),
        )
        return None, None


def _warmup_one(server, ref):
    ref = ref or {}
    provider = (ref.get("provider") or "").strip().lower()
    server_id = server.get("id")
    cache_key = _cache_key_for_ref(server_id, ref)

    if not cache_key:
        return "skipped"

    if _is_cache_fresh(cache_key):
        return "hit"

    if provider == "plex":
        fetched = _fetch_plex(server, ref)
    elif provider == "jellyfin":
        fetched = _fetch_jellyfin(server, ref)
    else:
        return "skipped"

    if not fetched:
        return "error"

    content, content_type = fetched
    _write_artwork_cache(cache_key, content, content_type)
    return "warmed"


def run(task_id: int, db):
    task_logs(task_id, "info", "Task warmup_artwork_cache started")
    log.info("=== WARMUP ARTWORK CACHE : STARTING ===")

    servers = _load_servers(db)
    if not servers:
        msg = "No Plex/Jellyfin server with token found. Artwork warmup skipped."
        task_logs(task_id, "info", msg)
        log.info(msg)
        return {"candidates": 0, "unique_refs": 0, "warmed": 0, "hit": 0, "skipped": 0, "errors": 0}

    candidates = _load_candidates(db)

    seen = set()
    warmed = 0
    hit = 0
    skipped = 0
    errors = 0

    for row in candidates:
        server_id = _safe_int(row.get("server_id"))
        server = servers.get(server_id)
        if not server:
            skipped += 1
            continue

        poster_ref, backdrop_ref = _resolve_refs(db, row)

        for ref in (poster_ref, backdrop_ref):
            if not ref:
                continue

            cache_key = _cache_key_for_ref(server_id, ref)
            if not cache_key or cache_key in seen:
                continue

            seen.add(cache_key)

            try:
                result = _warmup_one(server, ref)
                if result == "warmed":
                    warmed += 1
                elif result == "hit":
                    hit += 1
                elif result == "skipped":
                    skipped += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                log.warning(f"Unable to warm artwork cache for server={server_id}: {e}", exc_info=True)

    msg = (
        f"Artwork warmup finished: candidates={len(candidates)}, unique_refs={len(seen)}, "
        f"warmed={warmed}, already_cached={hit}, skipped={skipped}, errors={errors}."
    )
    task_logs(task_id, "success" if errors == 0 else "warning", msg)
    log.info(msg)
    log.info("=== WARMUP ARTWORK CACHE : FINISHED ===")

    return {
        "candidates": len(candidates),
        "unique_refs": len(seen),
        "warmed": warmed,
        "hit": hit,
        "skipped": skipped,
        "errors": errors,
    }
