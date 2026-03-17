# Auto-split from app.py (keep URLs/endpoints intact)
import os
import json
import time
import re
import math
import platform
import ipaddress
import uuid
import threading
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import xml.etree.ElementTree as ET
from flask import (
    render_template, g, request, redirect, url_for, flash, session,
    Response, current_app, jsonify, make_response, abort,
)

from db_manager import DBManager
from logging_utils import get_logger, read_last_logs, read_all_logs
from tasks_engine import run_task, start_scheduler, run_task_sequence, run_task_by_name, enqueue_task
from mailing_utils import build_user_context, render_mail
from discord_utils import is_discord_ready, validate_discord_bot_token
from core.i18n import get_translator, get_available_languages
from core.backup import BackupConfig, ensure_backup_dir, create_backup_file, list_backups, restore_backup_file
from werkzeug.security import generate_password_hash, check_password_hash

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg

task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

monitoring_logger = get_logger("monitoring_overview")

_SERVER_RESOURCE_CACHE = {}
_SERVER_RESOURCE_CACHE_TTL = 10  # secondes


def _normalize_pct(value):
    try:
        value = float(value)
    except Exception:
        return None

    if math.isnan(value) or math.isinf(value):
        return None

    if value < 0:
        value = 0.0
    if value > 100:
        value = 100.0

    return round(value, 1)


def _candidate_bases(server_row):
    bases = []
    invalid_literals = {"", "none", "null", "undefined"}

    for key in ("url", "local_url", "public_url"):
        raw = server_row.get(key)
        if not raw:
            continue

        base = str(raw).strip().rstrip("/")
        if base.lower() in invalid_literals:
            continue

        if not (base.startswith("http://") or base.startswith("https://")):
            continue

        if base not in bases:
            bases.append(base)

    return bases


def _empty_server_resource_stats(note=None):
    return {
        "server_cpu_pct": None,
        "server_ram_pct": None,
        "server_resource_available": False,
        "server_resource_note": note,
    }


def _fetch_plex_resource_stats(server_row, timeout=4):
    token = (server_row.get("token") or "").strip()
    if not token:
        return _empty_server_resource_stats()

    for base in _candidate_bases(server_row):
        try:
            r = requests.get(
                f"{base}/statistics/resources",
                params={
                    "timespan": 6,
                    "X-Plex-Token": token,
                },
                headers={"Accept": "application/xml"},
                timeout=timeout,
            )
            r.raise_for_status()

            root = ET.fromstring(r.text)

            samples = []
            for node in root.iter():
                tag = str(node.tag).lower()
                if tag.endswith("statisticsresource") or tag.endswith("statisticsresources"):
                    samples.append(node)

            if not samples:
                continue

            latest = samples[-1]

            cpu_pct = _normalize_pct(latest.attrib.get("processCpuUtilization"))
            ram_pct = _normalize_pct(latest.attrib.get("processMemoryUtilization"))

            return {
                "server_cpu_pct": cpu_pct,
                "server_ram_pct": ram_pct,
                "server_resource_available": (cpu_pct is not None or ram_pct is not None),
                "server_resource_note": None,
            }

        except Exception:
            continue

    return _empty_server_resource_stats()


def _fetch_jellyfin_resource_stats(server_row, timeout=4):
    """
    Support UI propre pour Jellyfin, sans inventer de métriques.
    Avec les données actuellement disponibles dans VODUM (URL + token),
    on ne dispose pas ici d'un endpoint fiable équivalent à Plex pour
    récupérer directement le % CPU / RAM du process serveur.
    """
    return _empty_server_resource_stats(note="unavailable")


def _fetch_server_resource_stats(server_row, timeout=4):
    try:
        server_id = int(server_row.get("id") or 0)
    except Exception:
        server_id = 0

    now_ts = time.time()
    cached = _SERVER_RESOURCE_CACHE.get(server_id)
    if cached and (now_ts - cached["ts"] < _SERVER_RESOURCE_CACHE_TTL):
        return dict(cached["value"])

    provider = (server_row.get("type") or "").strip().lower()

    if provider == "plex":
        value = _fetch_plex_resource_stats(server_row, timeout=timeout)
    elif provider == "jellyfin":
        value = _fetch_jellyfin_resource_stats(server_row, timeout=timeout)
    else:
        value = _empty_server_resource_stats()

    _SERVER_RESOURCE_CACHE[server_id] = {
        "ts": now_ts,
        "value": dict(value),
    }
    return dict(value)


def _apply_server_resource_stats(rows, resource_by_server, server_id_key="server_id"):
    for row in rows or []:
        try:
            server_id = int(row.get(server_id_key) or 0)
        except Exception:
            server_id = 0

        resource = resource_by_server.get(server_id) or _empty_server_resource_stats()

        row["server_cpu_pct"] = resource.get("server_cpu_pct")
        row["server_ram_pct"] = resource.get("server_ram_pct")
        row["server_resource_available"] = bool(resource.get("server_resource_available"))
        row["server_resource_note"] = resource.get("server_resource_note")

def _build_history_poster_url(row):
    row = dict(row or {})
    try:
        server_id = int(row.get("server_id") or 0)
    except Exception:
        server_id = 0

    if server_id <= 0:
        return None

    provider = (row.get("provider") or "").strip().lower()
    raw = row.get("raw_json")
    media_type = (row.get("media_type") or "").strip().lower()
    media_group_key = (row.get("media_group_key") or "").strip().lower()

    is_series = (
        media_group_key.startswith("series:")
        or media_type in ("serie", "series", "show", "episode", "tv", "season")
    )

    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

    if provider == "plex":
        attrs = (data.get("VideoOrTrack") or {})

        if is_series:
            poster_path = (
                attrs.get("grandparentThumb")
                or attrs.get("parentThumb")
                or attrs.get("thumb")
            )
        else:
            poster_path = (
                attrs.get("thumb")
                or attrs.get("parentThumb")
                or attrs.get("grandparentThumb")
            )

        # Fallback import Tautulli
        if not poster_path:
            if is_series:
                grandparent_rating_key = str(attrs.get("grandparentRatingKey") or "").strip()
                parent_rating_key = str(attrs.get("parentRatingKey") or "").strip()
                media_key = str(row.get("media_key") or "").strip()

                if grandparent_rating_key:
                    poster_path = f"/library/metadata/{grandparent_rating_key}/thumb"
                elif parent_rating_key:
                    poster_path = f"/library/metadata/{parent_rating_key}/thumb"
                elif media_key:
                    poster_path = f"/library/metadata/{media_key}/thumb"
            else:
                media_key = str(row.get("media_key") or "").strip()
                if media_key:
                    poster_path = f"/library/metadata/{media_key}/thumb"

        if poster_path:
            return url_for(
                "api_monitoring_poster",
                server_id=server_id,
                path=poster_path,
            )

    elif provider == "jellyfin":
        now = (data.get("NowPlayingItem") or data.get("Item") or {})

        if is_series:
            poster_item_id = now.get("SeriesId") or now.get("Id") or row.get("media_key")
        else:
            poster_item_id = now.get("Id") or now.get("SeriesId") or row.get("media_key")

        if poster_item_id:
            return url_for(
                "api_monitoring_poster",
                server_id=server_id,
                item_id=str(poster_item_id),
            )

    return None

def _build_history_backdrop_url(row):
    row = dict(row or {})
    try:
        server_id = int(row.get("server_id") or 0)
    except Exception:
        server_id = 0

    if server_id <= 0:
        return None

    provider = (row.get("provider") or "").strip().lower()
    raw = row.get("raw_json")
    media_type = (row.get("media_type") or "").strip().lower()
    media_group_key = (row.get("media_group_key") or "").strip().lower()

    is_series = (
        media_group_key.startswith("series:")
        or media_type in ("serie", "series", "show", "episode", "tv", "season")
    )

    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

    if provider == "plex":
        attrs = (data.get("VideoOrTrack") or {})

        if is_series:
            backdrop_path = (
                attrs.get("grandparentArt")
                or attrs.get("art")
                or attrs.get("parentArt")
            )
        else:
            backdrop_path = (
                attrs.get("art")
                or attrs.get("thumb")
                or attrs.get("parentArt")
            )

        if not backdrop_path:
            if is_series:
                grandparent_rating_key = str(attrs.get("grandparentRatingKey") or "").strip()
                parent_rating_key = str(attrs.get("parentRatingKey") or "").strip()
                media_key = str(row.get("media_key") or "").strip()

                if grandparent_rating_key:
                    backdrop_path = f"/library/metadata/{grandparent_rating_key}/art"
                elif parent_rating_key:
                    backdrop_path = f"/library/metadata/{parent_rating_key}/art"
                elif media_key:
                    backdrop_path = f"/library/metadata/{media_key}/art"
            else:
                media_key = str(row.get("media_key") or "").strip()
                if media_key:
                    backdrop_path = f"/library/metadata/{media_key}/art"

        if backdrop_path:
            return url_for(
                "api_monitoring_poster",
                server_id=server_id,
                path=backdrop_path,
            )

    elif provider == "jellyfin":
        now = (data.get("NowPlayingItem") or data.get("Item") or {})

        if is_series:
            backdrop_item_id = now.get("SeriesId") or now.get("Id") or row.get("media_key")
        else:
            backdrop_item_id = now.get("Id") or now.get("SeriesId") or row.get("media_key")

        if backdrop_item_id:
            return url_for(
                "api_monitoring_poster",
                server_id=server_id,
                item_id=str(backdrop_item_id),
                image_type="Backdrop",
                image_index="0",
                w="900",
                q="80",
            )

    return None

def register(app):
    @app.route("/monitoring")
    def monitoring_page():
        db = get_db()
        tab = request.args.get("tab", "overview")

        # Une session est considérée "live" si vue dans les 120 dernières secondes
        live_window_seconds = 120
        live_window_sql = f"-{live_window_seconds} seconds"

        # --------------------------
        # Serveurs (statuts) (utilisé partout)
        # --------------------------
        servers = db.query(
            """
            SELECT id, name, type, url, local_url, public_url, token, status, last_checked
            FROM servers
            WHERE type IN ('plex','jellyfin')
            ORDER BY type, name
            """
        )
        servers = [dict(r) for r in (servers or [])]

        configured_server_count = len(servers or [])

        server_resource_stats = {}
        if tab in ("overview", "now_playing", "servers"):
            for srv in servers:
                try:
                    sid = int(srv.get("id") or 0)
                except Exception:
                    sid = 0
                server_resource_stats[sid] = _fetch_server_resource_stats(srv)

        server_stats = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status='up' THEN 1 ELSE 0 END) AS online,
              SUM(CASE WHEN status='down' THEN 1 ELSE 0 END) AS offline,
              COUNT(*) AS total
            FROM servers
            WHERE type IN ('plex','jellyfin')
            """
        ) or {"online": 0, "offline": 0, "total": 0}
        server_stats = dict(server_stats) if server_stats else {"online": 0, "offline": 0, "total": 0}

        sessions_stats = {"live_sessions": 0, "transcodes": 0, "direct_plays": 0}
        live_servers = []
        sessions = []
        events = []
        stats_7d = {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
        top_users_30d = []
        top_content_30d = []
        top_movies_30d = []
        concurrent_7d = {"peak_streams": 0}

        # --------------------------
        # Données "live" uniquement pour overview / now_playing
        # --------------------------
        if tab in ("overview", "now_playing"):
            sessions_stats = db.query_one(
                """
                SELECT
                  COUNT(*) AS live_sessions,
                  SUM(CASE WHEN is_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM media_sessions
                WHERE datetime(last_seen_at) >= datetime('now', ?)
                """,
                (live_window_sql,),
            ) or {"live_sessions": 0, "transcodes": 0}
            sessions_stats = dict(sessions_stats) if sessions_stats else {"live_sessions": 0, "transcodes": 0}

            sessions_stats["live_sessions"] = int(sessions_stats.get("live_sessions") or 0)
            sessions_stats["transcodes"] = int(sessions_stats.get("transcodes") or 0)
            sessions_stats["direct_plays"] = max(
                0,
                sessions_stats["live_sessions"] - sessions_stats["transcodes"]
            )

            live_servers = db.query(
                """
                SELECT
                  ms.server_id,
                  s.name AS server_name,
                  COUNT(*) AS live_sessions,
                  SUM(CASE WHEN ms.is_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM media_sessions ms
                JOIN servers s ON s.id = ms.server_id
                WHERE s.type IN ('plex','jellyfin')
                  AND datetime(ms.last_seen_at) >= datetime('now', ?)
                GROUP BY ms.server_id, s.name
                HAVING COUNT(*) > 0
                ORDER BY transcodes DESC, live_sessions DESC, s.name ASC
                LIMIT 6
                """,
                (live_window_sql,),
            )

            live_servers = [dict(r) for r in (live_servers or [])]
            for row in live_servers:
                row["live_sessions"] = int(row.get("live_sessions") or 0)
                row["transcodes"] = int(row.get("transcodes") or 0)
                row["direct_plays"] = max(0, row["live_sessions"] - row["transcodes"])

            _apply_server_resource_stats(live_servers, server_resource_stats)

            # Snapshot affiché, seulement quand on est sur une vue live
            try:
                live_now = int(sessions_stats.get("live_sessions") or 0)
                transcodes_now = int(sessions_stats.get("transcodes") or 0)

                db.execute(
                    """
                    INSERT INTO monitoring_snapshots (ts, live_sessions, transcodes)
                    SELECT CURRENT_TIMESTAMP, ?, ?
                    WHERE NOT EXISTS (
                      SELECT 1
                      FROM monitoring_snapshots
                      WHERE ts >= datetime('now', '-30 seconds')
                    )
                    """,
                    (live_now, transcodes_now),
                )

                db.execute("DELETE FROM monitoring_snapshots WHERE ts < datetime('now','-30 days')")
            except Exception as e:
                monitoring_logger.warning(f"Could not write monitoring snapshot (overview): {e}")

            sessions = db.query(
                """
                SELECT
                  ms.id,
                  ms.server_id,
                  s.name AS server_name,
                  s.type AS provider,

                  ms.media_type,
                  ms.title,
                  ms.grandparent_title,
                  ms.parent_title,

                  ms.state,
                  ms.progress_ms,
                  ms.duration_ms,

                  ms.client_name,
                  mu.username AS username,
                  ms.is_transcode,
                  ms.last_seen_at,

                  ms.raw_json,
                  ms.media_key
                FROM media_sessions ms
                JOIN servers s ON s.id = ms.server_id
                LEFT JOIN media_users mu ON mu.id = ms.media_user_id
                WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
                ORDER BY datetime(ms.last_seen_at) DESC
                """,
                (live_window_sql,),
            )

            def _safe_int(v):
                try:
                    if v is None:
                        return None
                    return int(v)
                except Exception:
                    return None

            def _fmt_ms(ms: Optional[int]) -> str:
                try:
                    ms = int(ms or 0)
                except Exception:
                    ms = 0
                if ms < 0:
                    ms = 0
                total_sec = ms // 1000
                h = total_sec // 3600
                m = (total_sec % 3600) // 60
                s = total_sec % 60
                return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

            sessions = [dict(r) for r in sessions]
            _apply_server_resource_stats(sessions, server_resource_stats)

            for s in sessions:
                try:
                    prog = int(s.get("progress_ms") or 0)
                except Exception:
                    prog = 0

                try:
                    dur = int(s.get("duration_ms") or 0)
                except Exception:
                    dur = 0

                if prog < 0:
                    prog = 0
                if dur < 0:
                    dur = 0

                if dur > 0:
                    pct = (prog / dur) * 100.0
                    if pct < 0:
                        pct = 0.0
                    if pct > 100:
                        pct = 100.0
                    s["progress_pct"] = round(pct, 1)
                    s["progress_text"] = f"{_fmt_ms(prog)} / {_fmt_ms(dur)}"
                    s["remaining_text"] = _fmt_ms(max(0, dur - prog))
                else:
                    s["progress_pct"] = 0
                    s["progress_text"] = None
                    s["remaining_text"] = None

                s["season_number"] = None
                s["episode_number"] = None
                s["episode_code"] = None
                s["poster_url"] = None

                raw = s.get("raw_json")
                if not raw:
                    continue

                try:
                    data = json.loads(raw)
                except Exception:
                    data = {}

                provider = (s.get("provider") or "").lower()

                if provider == "plex":
                    attrs = (data.get("VideoOrTrack") or {})

                    season = _safe_int(attrs.get("parentIndex"))
                    episode = _safe_int(attrs.get("index"))

                    s["season_number"] = season
                    s["episode_number"] = episode

                    if season is not None and episode is not None:
                        s["episode_code"] = f"S{season:02d}E{episode:02d}"
                    elif season is not None:
                        s["episode_code"] = f"S{season}"

                    poster_path = (
                        attrs.get("grandparentThumb")
                        or attrs.get("parentThumb")
                        or attrs.get("thumb")
                    )
                    if poster_path:
                        s["poster_url"] = url_for(
                            "api_monitoring_poster",
                            server_id=s["server_id"],
                            path=poster_path,
                        )

                elif provider == "jellyfin":
                    now = (data.get("NowPlayingItem") or {})

                    season = _safe_int(now.get("ParentIndexNumber"))
                    episode = _safe_int(now.get("IndexNumber"))

                    s["season_number"] = season
                    s["episode_number"] = episode

                    if season is not None and episode is not None:
                        s["episode_code"] = f"S{season:02d}E{episode:02d}"
                    elif season is not None:
                        s["episode_code"] = f"S{season}"

                    poster_item_id = now.get("SeriesId") or now.get("Id") or s.get("media_key")
                    if poster_item_id:
                        s["poster_url"] = url_for(
                            "api_monitoring_poster",
                            server_id=s["server_id"],
                            item_id=str(poster_item_id),
                        )

        # --------------------------
        # Latest events for overview + activity
        # --------------------------
        if tab in ("overview", "activity"):
            events = db.query(
                """
                SELECT
                  e.id,
                  s.name AS server_name,
                  e.provider,
                  e.event_type,
                  e.ts,
                  e.title
                FROM media_events e
                JOIN servers s ON s.id = e.server_id
                ORDER BY e.ts DESC
                LIMIT 30
                """
            )

        # --------------------------
        # Données overview uniquement
        # --------------------------
        if tab == "overview":

            stats_7d = db.query_one(
                """
                WITH base AS (
                  SELECT
                    h.server_id,
                    h.started_at,
                    h.stopped_at,
                    h.media_key,
                    h.watch_ms,
                    h.duration_ms,
                    COALESCE(
                      CAST(mu.vodum_user_id AS TEXT),
                      'media:' || CAST(mu.id AS TEXT)
                    ) AS viewer_id,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     COALESCE(CAST(mu.vodum_user_id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  LEFT JOIN media_users mu ON mu.id = h.media_user_id
                  WHERE h.stopped_at >= datetime('now', '-7 days')
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(viewer_id) AS viewer_id,
                    MAX(watch_ms_capped) AS watch_ms
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  COUNT(*) AS sessions,
                  COUNT(DISTINCT viewer_id) AS active_users,
                  COALESCE(SUM(watch_ms), 0) AS total_watch_ms,
                  AVG(NULLIF(watch_ms, 0)) AS avg_watch_ms
                FROM plays
                """
            ) or {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
            stats_7d = dict(stats_7d) if stats_7d else {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}

            top_users_30d = db.query(
                """
                WITH base AS (
                  SELECT
                    h.server_id,
                    h.started_at,
                    h.stopped_at,
                    h.media_key,
                    COALESCE(vu.username, mu.username, '-') AS username,
                    COALESCE(CAST(vu.id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) AS viewer_id,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     COALESCE(CAST(vu.id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  LEFT JOIN media_users mu ON mu.id = h.media_user_id
                  LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
                  WHERE h.stopped_at >= datetime('now', '-30 days')
                ),
                plays AS (
                  SELECT
                    viewer_id,
                    MAX(username) AS username,
                    play_key,
                    MAX(watch_ms_capped) AS watch_ms
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  username,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms), 0) AS watch_ms
                FROM plays
                GROUP BY viewer_id
                ORDER BY watch_ms DESC
                LIMIT 10
                """
            )

            top_content_30d = db.query(
                """
                WITH base AS (
                  SELECT
                    h.server_id,
                    s.type AS provider,
                    h.started_at,
                    h.stopped_at,
                    TRIM(h.grandparent_title) AS series_title,
                    h.media_key,
                    h.media_type,
                    h.raw_json,
                    COALESCE(
                      CAST(mu.vodum_user_id AS TEXT),
                      'media:' || CAST(mu.id AS TEXT)
                    ) AS viewer_id,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     COALESCE(CAST(mu.vodum_user_id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  LEFT JOIN media_users mu ON mu.id = h.media_user_id
                  LEFT JOIN servers s ON s.id = h.server_id
                  WHERE h.stopped_at >= datetime('now', '-30 days')
                    AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(provider) AS provider,
                    MAX(series_title) AS series_title,
                    MAX(media_key) AS media_key,
                    MAX(media_type) AS media_type,
                    MAX(raw_json) AS raw_json,
                    MAX(viewer_id) AS viewer_id,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(stopped_at) AS stopped_at
                  FROM base
                  GROUP BY play_key
                ),
                agg AS (
                  SELECT
                    series_title AS title,
                    COUNT(DISTINCT viewer_id) AS viewers,
                    COUNT(*) AS plays,
                    COALESCE(SUM(watch_ms), 0) AS watch_ms
                  FROM plays
                  GROUP BY series_title
                ),
                latest AS (
                  SELECT
                    series_title AS title,
                    server_id,
                    provider,
                    media_key,
                    media_type,
                    raw_json,
                    ROW_NUMBER() OVER (
                      PARTITION BY series_title
                      ORDER BY stopped_at DESC
                    ) AS rn
                  FROM plays
                )
                SELECT
                  a.title,
                  a.viewers,
                  a.plays,
                  a.watch_ms,
                  l.server_id,
                  l.provider,
                  l.media_key,
                  l.media_type,
                  l.raw_json,
                  ('series:' || LOWER(TRIM(a.title))) AS media_group_key
                FROM agg a
                LEFT JOIN latest l
                  ON l.title = a.title
                 AND l.rn = 1
                ORDER BY a.viewers DESC, a.watch_ms DESC
                LIMIT 10
                """
            )

            top_movies_30d = db.query(
                """
                WITH base AS (
                  SELECT
                    h.server_id,
                    s.type AS provider,
                    h.started_at,
                    h.stopped_at,
                    TRIM(COALESCE(NULLIF(h.title, ''), '-')) AS movie_title,
                    h.media_key,
                    h.media_type,
                    h.raw_json,
                    COALESCE(
                      CAST(mu.vodum_user_id AS TEXT),
                      'media:' || CAST(mu.id AS TEXT)
                    ) AS viewer_id,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     COALESCE(CAST(mu.vodum_user_id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  LEFT JOIN media_users mu ON mu.id = h.media_user_id
                  LEFT JOIN servers s ON s.id = h.server_id
                  WHERE h.stopped_at >= datetime('now', '-30 days')
                    AND TRIM(COALESCE(h.grandparent_title, '')) = ''
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(provider) AS provider,
                    MAX(movie_title) AS movie_title,
                    MAX(media_key) AS media_key,
                    MAX(media_type) AS media_type,
                    MAX(raw_json) AS raw_json,
                    MAX(viewer_id) AS viewer_id,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(stopped_at) AS stopped_at
                  FROM base
                  GROUP BY play_key
                ),
                agg AS (
                  SELECT
                    movie_title AS title,
                    COUNT(DISTINCT viewer_id) AS viewers,
                    COUNT(*) AS plays,
                    COALESCE(SUM(watch_ms), 0) AS watch_ms
                  FROM plays
                  GROUP BY movie_title
                ),
                latest AS (
                  SELECT
                    movie_title AS title,
                    server_id,
                    provider,
                    media_key,
                    media_type,
                    raw_json,
                    ROW_NUMBER() OVER (
                      PARTITION BY movie_title
                      ORDER BY stopped_at DESC
                    ) AS rn
                  FROM plays
                )
                SELECT
                  a.title,
                  a.viewers,
                  a.plays,
                  a.watch_ms,
                  l.server_id,
                  l.provider,
                  l.media_key,
                  l.media_type,
                  l.raw_json,
                  ('movie:' || LOWER(TRIM(a.title))) AS media_group_key
                FROM agg a
                LEFT JOIN latest l
                  ON l.title = a.title
                 AND l.rn = 1
                ORDER BY a.viewers DESC, a.watch_ms DESC
                LIMIT 10
                """
            )

            top_content_30d = [dict(r) for r in (top_content_30d or [])]
            for item in top_content_30d:
                item["backdrop_url"] = _build_history_backdrop_url(item)

            top_movies_30d = [dict(r) for r in (top_movies_30d or [])]
            for item in top_movies_30d:
                item["backdrop_url"] = _build_history_backdrop_url(item)

            concurrent_7d = db.query_one(
                """
                SELECT COALESCE(MAX(live_sessions), 0) AS peak_streams
                FROM monitoring_snapshots
                WHERE ts >= datetime('now', '-7 days')
                """
            ) or {"peak_streams": 0}
            concurrent_7d = dict(concurrent_7d) if concurrent_7d else {"peak_streams": 0}

            live_now = int(sessions_stats.get("live_sessions") or 0)
            peak = int(concurrent_7d.get("peak_streams") or 0)
            concurrent_7d["peak_streams"] = max(peak, live_now)


        sort_key = None
        sort_dir = None


        # --------------------------
        # Tabs data
        # --------------------------
        policies = []
        rows = []
        filters = {}
        pagination = None
        library_top_cards = []
        library_users = []
        library_range = "30d"
        library_user = "all"
        hidden_libraries_count = 0

        policy_dashboard = {}
        policy_hits_30d = []
        policy_rule_breakdown_30d = []
        policy_provider_breakdown_30d = []
        policy_scope_breakdown = []
        policy_top_users_30d = []
        policy_recent_enforcements = []
        policy_tracked_state = {}
        

        if tab == "history":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            q = (request.args.get("q") or "").strip()
            provider = (request.args.get("provider") or "").strip()
            media_type = (request.args.get("media_type") or "").strip()
            playback = (request.args.get("playback") or "").strip()
            server_id = request.args.get("server", type=int)

            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "date").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "desc").strip().lower()

            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"

            # whitelist anti-injection SQL (IMPORTANT)
            SORT_MAP = {
                "date": "h.stopped_at",
                "user": "mu.username",
                "server": "s.name",
                "media": "h.title",
                "type": "h.media_type",
                "playback": "playback_type",   # alias défini dans SELECT
                "device": "h.device",
                "duration": "h.watch_ms",
            }
            if sort_key not in SORT_MAP:
                sort_key = "date"

            order_col = SORT_MAP[sort_key]
            order_sql = f"{order_col} {'ASC' if sort_dir == 'asc' else 'DESC'}"


            where = ["1=1"]
            params = []

            if q:
                where.append("(h.title LIKE ? OR h.grandparent_title LIKE ?)")
                params += [f"%{q}%", f"%{q}%"]
            if provider:
                where.append("s.type = ?")
                params.append(provider)
            if media_type:
                where.append("h.media_type = ?")
                params.append(media_type)
            if playback:
                pb = playback.lower()
                if pb in ("transcode", "transcoding"):
                    where.append("h.was_transcode = 1")
                elif pb in ("directplay", "direct", "direct_play"):
                    where.append("h.was_transcode = 0")
            if server_id:
                where.append("h.server_id = ?")
                params.append(server_id)

            where_sql = " AND ".join(where)

            total = db.query_one(
                f"""
                SELECT COUNT(*) AS cnt
                FROM media_session_history h
                JOIN servers s ON s.id = h.server_id
                WHERE {where_sql}
                """,
                tuple(params),
            ) or {"cnt": 0}
            total = dict(total) if total else {"cnt": 0}

            rows = db.query(
                f"""
                SELECT
                  h.stopped_at,
                  s.name AS server_name,
                  s.type AS provider,
                  mu.username,
                  h.title,
                  h.grandparent_title,
                  h.media_type,
                  CASE WHEN h.was_transcode = 1 THEN 'transcode' ELSE 'directplay' END AS playback_type,
                  h.device,
                  h.client_name,
                  h.watch_ms
                FROM media_session_history h
                JOIN servers s ON s.id = h.server_id
                LEFT JOIN media_users mu ON mu.id = h.media_user_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                tuple(params + [offset]),
            )

            rows = [dict(r) for r in rows]
            for r in rows:
                ms = r.get("watch_ms") or 0
                r["watch_time"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"

            total_rows = int(total.get("cnt") or 0)
            total_pages = max(1, (total_rows + per_page - 1) // per_page)

            def build_url(p):
                args = dict(request.args)
                args["tab"] = "history"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = {
                "page": page,
                "total_pages": total_pages,
                "total_rows": total_rows,
                "first_url": build_url(1),
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
                "last_url": build_url(total_pages),
            }

            filters = {
                "q": q,
                "provider": provider,
                "media_type": media_type,
                "playback": playback,
                "server": server_id,
            }

        elif tab == "users":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            q = (request.args.get("q") or "").strip()

            # --------------------------
            # Total rows (même logique de groupement que la liste)
            # --------------------------
            if q:
                like = f"%{q}%"
                total = db.query_one(
                    """
                    WITH base AS (
                      SELECT
                        h.media_user_id AS media_user_id,
                        mu.username AS mu_username,
                        mu.vodum_user_id,
                        CASE
                          WHEN mu.vodum_user_id IS NOT NULL THEN ('v:' || mu.vodum_user_id)
                          ELSE ('m:' || mu.id)
                        END AS group_key
                      FROM media_session_history h
                      JOIN media_users mu ON mu.id = h.media_user_id
                      WHERE h.media_user_id IS NOT NULL
                    ),
                    names AS (
                      SELECT
                        b.group_key,
                        MAX(b.vodum_user_id) AS vodum_user_id,
                        MIN(b.media_user_id) AS user_id,
                        COALESCE(vu.username, MIN(b.mu_username)) AS username
                      FROM base b
                      LEFT JOIN vodum_users vu ON vu.id = b.vodum_user_id
                      GROUP BY b.group_key
                    )
                    SELECT COUNT(*) AS cnt
                    FROM names n
                    LEFT JOIN vodum_users vu ON vu.id = n.vodum_user_id
                    WHERE (
                      COALESCE(n.username,'') LIKE ? OR
                      COALESCE(vu.username,'') LIKE ? OR
                      COALESCE(vu.email,'') LIKE ? OR
                      COALESCE(vu.second_email,'') LIKE ? OR
                      COALESCE(vu.firstname,'') LIKE ? OR
                      COALESCE(vu.lastname,'') LIKE ? OR
                      COALESCE(vu.notes,'') LIKE ?
                    )
                    """,
                    (like, like, like, like, like, like, like),
                ) or {"cnt": 0}
            else:
                total = db.query_one(
                    """
                    WITH base AS (
                      SELECT
                        CASE
                          WHEN mu.vodum_user_id IS NOT NULL THEN ('v:' || mu.vodum_user_id)
                          ELSE ('m:' || mu.id)
                        END AS group_key
                      FROM media_session_history h
                      JOIN media_users mu ON mu.id = h.media_user_id
                      WHERE h.media_user_id IS NOT NULL
                    )
                    SELECT COUNT(DISTINCT group_key) AS cnt
                    FROM base
                    """
                ) or {"cnt": 0}


            total = dict(total) if total else {"cnt": 0}

            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "last").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "desc").strip().lower()
            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"

            SORT_MAP = {
                "user": "n.username",
                "last": "lr.last_watch_at",
                "plays": "a.total_plays",
                "watch": "a.watch_ms",
                "ip": "lr.ip",
                # "platform": "COALESCE(lr.device, lr.client_product, '-')",
                "player": "COALESCE(lr.client_name, lr.client_product, '-')",
            }
            if sort_key not in SORT_MAP:
                sort_key = "last"

            col = SORT_MAP[sort_key]
            direction = "ASC" if sort_dir == "asc" else "DESC"
            order_sql = f"({col} IS NULL) ASC, {col} {direction}"

            # filtre username
            end_where = ""
            params = []
            if q:
                like = f"%{q}%"
                end_where = """
                WHERE (
                  COALESCE(n.username,'') LIKE ? OR
                  COALESCE(vu.username,'') LIKE ? OR
                  COALESCE(vu.email,'') LIKE ? OR
                  COALESCE(vu.second_email,'') LIKE ? OR
                  COALESCE(vu.firstname,'') LIKE ? OR
                  COALESCE(vu.lastname,'') LIKE ? OR
                  COALESCE(vu.notes,'') LIKE ?
                )
                """

                params.extend([like, like, like, like, like, like, like])


            rows = db.query(
                f"""
                WITH base AS (
                  SELECT
                    h.server_id,
                    h.started_at,
                    h.stopped_at,
                    h.media_key,
                    h.watch_ms,
                    h.duration_ms,
                    h.ip,
                    h.device,
                    h.client_name,
                    h.client_product,
                    h.media_user_id AS media_user_id,
                    mu.username AS mu_username,
                    mu.vodum_user_id,
                    CASE
                      WHEN mu.vodum_user_id IS NOT NULL THEN ('v:' || mu.vodum_user_id)
                      ELSE ('m:' || mu.id)
                    END AS group_key,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     CASE
                       WHEN mu.vodum_user_id IS NOT NULL THEN ('v:' || mu.vodum_user_id)
                       ELSE ('m:' || mu.id)
                     END || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  JOIN media_users mu ON mu.id = h.media_user_id
                  WHERE h.media_user_id IS NOT NULL
                ),
                plays AS (
                  SELECT
                    group_key,
                    play_key,
                    MAX(stopped_at) AS stopped_at,
                    MAX(watch_ms_capped) AS watch_ms
                  FROM base
                  GROUP BY play_key
                ),
                agg AS (
                  SELECT
                    group_key,
                    MAX(stopped_at) AS last_watch_at,
                    COUNT(*) AS total_plays,
                    COALESCE(SUM(watch_ms), 0) AS watch_ms
                  FROM plays
                  GROUP BY group_key
                ),

ranked AS (
                  SELECT
                    group_key,
                    stopped_at,
                    ip,
                    device,
                    client_name,
                    client_product,
                    ROW_NUMBER() OVER (
                      PARTITION BY group_key
                      ORDER BY stopped_at DESC
                    ) AS rn
                  FROM base
                ),
                last_rows AS (
                  SELECT
                    group_key,
                    stopped_at AS last_watch_at,
                    ip,
                    device,
                    client_name,
                    client_product
                  FROM ranked
                  WHERE rn = 1
                ),
                names AS (
                  SELECT
                    b.group_key,
                    MAX(b.vodum_user_id) AS vodum_user_id,
                    MIN(b.media_user_id) AS user_id,
                    COALESCE(vu.username, MIN(b.mu_username)) AS username
                  FROM base b
                  LEFT JOIN vodum_users vu ON vu.id = b.vodum_user_id
                  GROUP BY b.group_key
                )
                SELECT
                  n.user_id AS user_id,
                  n.username AS username,
                  lr.last_watch_at,
                  a.total_plays,
                  a.watch_ms,
                  lr.ip AS last_ip,
                  COALESCE(lr.device, lr.client_product, '-') AS platform,
                  COALESCE(lr.client_name, lr.client_product, '-') AS player
                FROM agg a
                JOIN last_rows lr ON lr.group_key = a.group_key
                JOIN names n ON n.group_key = a.group_key
                LEFT JOIN vodum_users vu ON vu.id = n.vodum_user_id
                {end_where}
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                tuple(params + [offset]),
            )


            rows = [dict(r) for r in rows]
            for u in rows:
                ms = u.get("watch_ms") or 0
                u["watch_time"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"
                if not u.get("last_ip"):
                    u["last_ip"] = "-"

            # Pagination
            total_rows = int(total.get("cnt") or 0)
            total_pages = max(1, (total_rows + per_page - 1) // per_page)

            def build_url(p):
                args = dict(request.args)
                args["tab"] = "users"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = {
                "page": page,
                "total_pages": total_pages,
                "total_rows": total_rows,
                "first_url": build_url(1),
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
                "last_url": build_url(total_pages),
            }

        elif tab == "policies":
            policies = db.query("""
                SELECT
                  p.*,
                  s.name AS server_name,
                  vu.username AS scope_username
                FROM stream_policies p
                LEFT JOIN servers s
                  ON s.id = p.server_id
                LEFT JOIN vodum_users vu
                  ON (p.scope_type = 'user' AND vu.id = p.scope_id)
                ORDER BY p.is_enabled DESC, p.priority ASC, p.id DESC
            """)

            policies = [dict(r) for r in policies]

            # Parse rule JSON + detect system-managed / locked policies
            system_count = 0
            locked_count = 0
            subscription_managed_count = 0

            for p in policies:
                try:
                    p["_rule"] = json.loads(p.get("rule_value_json") or "{}")
                except Exception:
                    p["_rule"] = {}

                p["_is_system"] = bool(p["_rule"].get("system_tag"))
                p["_is_locked"] = bool(p["_rule"].get("locked"))
                p["_subscription_name"] = p["_rule"].get("subscription_name") or ""

                if p["_is_system"]:
                    system_count += 1
                if p["_is_locked"]:
                    locked_count += 1
                if p["_subscription_name"]:
                    subscription_managed_count += 1

            edit_policy = None
            edit_policy_id = request.args.get("edit_policy_id", type=int)
            if edit_policy_id:
                ep = db.query_one("SELECT * FROM stream_policies WHERE id = ?", (edit_policy_id,))
                if ep:
                    ep = dict(ep)
                    try:
                        ep["_rule"] = json.loads(ep.get("rule_value_json") or "{}")
                    except Exception:
                        ep["_rule"] = {}
                    edit_policy = ep

            base_policy_stats = db.query_one("""
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN is_enabled = 1 THEN 1 ELSE 0 END) AS enabled,
                  SUM(CASE WHEN is_enabled = 0 THEN 1 ELSE 0 END) AS disabled,
                  SUM(CASE WHEN scope_type = 'global' THEN 1 ELSE 0 END) AS scope_global,
                  SUM(CASE WHEN scope_type = 'server' THEN 1 ELSE 0 END) AS scope_server,
                  SUM(CASE WHEN scope_type = 'user' THEN 1 ELSE 0 END) AS scope_user,
                  SUM(CASE WHEN provider = 'plex' THEN 1 ELSE 0 END) AS provider_plex,
                  SUM(CASE WHEN provider = 'jellyfin' THEN 1 ELSE 0 END) AS provider_jellyfin,
                  SUM(CASE WHEN provider IS NULL OR provider = '' THEN 1 ELSE 0 END) AS provider_both,
                  COUNT(DISTINCT CASE WHEN scope_type = 'user' THEN scope_id END) AS targeted_users,
                  COUNT(DISTINCT CASE WHEN server_id IS NOT NULL THEN server_id END) AS targeted_servers
                FROM stream_policies
            """) or {}

            base_policy_stats = dict(base_policy_stats or {})

            enforce_24h = db.query_one("""
                SELECT
                  COUNT(*) AS total_actions,
                  SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
                  SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count,
                  COUNT(DISTINCT policy_id) AS affected_policies,
                  COUNT(DISTINCT COALESCE(CAST(vodum_user_id AS TEXT), external_user_id)) AS affected_actors
                FROM stream_enforcements
                WHERE datetime(created_at) >= datetime('now', '-24 hours')
            """) or {}

            enforce_7d = db.query_one("""
                SELECT
                  COUNT(*) AS total_actions,
                  SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
                  SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count,
                  COUNT(DISTINCT policy_id) AS affected_policies,
                  COUNT(DISTINCT COALESCE(CAST(vodum_user_id AS TEXT), external_user_id)) AS affected_actors
                FROM stream_enforcements
                WHERE datetime(created_at) >= datetime('now', '-7 days')
            """) or {}

            enforce_24h = dict(enforce_24h or {})
            enforce_7d = dict(enforce_7d or {})

            policy_dashboard = {
                "total": int(base_policy_stats.get("total") or 0),
                "enabled": int(base_policy_stats.get("enabled") or 0),
                "disabled": int(base_policy_stats.get("disabled") or 0),
                "scope_global": int(base_policy_stats.get("scope_global") or 0),
                "scope_server": int(base_policy_stats.get("scope_server") or 0),
                "scope_user": int(base_policy_stats.get("scope_user") or 0),
                "provider_plex": int(base_policy_stats.get("provider_plex") or 0),
                "provider_jellyfin": int(base_policy_stats.get("provider_jellyfin") or 0),
                "provider_both": int(base_policy_stats.get("provider_both") or 0),
                "targeted_users": int(base_policy_stats.get("targeted_users") or 0),
                "targeted_servers": int(base_policy_stats.get("targeted_servers") or 0),
                "system_count": int(system_count or 0),
                "locked_count": int(locked_count or 0),
                "subscription_managed_count": int(subscription_managed_count or 0),
                "actions_24h": int(enforce_24h.get("total_actions") or 0),
                "warn_24h": int(enforce_24h.get("warn_count") or 0),
                "kill_24h": int(enforce_24h.get("kill_count") or 0),
                "affected_policies_24h": int(enforce_24h.get("affected_policies") or 0),
                "affected_actors_24h": int(enforce_24h.get("affected_actors") or 0),
                "actions_7d": int(enforce_7d.get("total_actions") or 0),
                "warn_7d": int(enforce_7d.get("warn_count") or 0),
                "kill_7d": int(enforce_7d.get("kill_count") or 0),
            }

            policy_scope_breakdown = db.query("""
                SELECT
                  scope_type AS label,
                  COUNT(*) AS value
                FROM stream_policies
                GROUP BY scope_type
                ORDER BY value DESC, label ASC
            """) or []
            policy_scope_breakdown = [dict(r) for r in policy_scope_breakdown]

            policy_provider_breakdown_30d = db.query("""
                SELECT
                  CASE
                    WHEN provider IS NULL OR provider = '' THEN 'both'
                    ELSE provider
                  END AS label,
                  COUNT(*) AS value
                FROM stream_enforcements
                WHERE datetime(created_at) >= datetime('now', '-30 days')
                GROUP BY
                  CASE
                    WHEN provider IS NULL OR provider = '' THEN 'both'
                    ELSE provider
                  END
                ORDER BY value DESC, label ASC
            """) or []
            policy_provider_breakdown_30d = [dict(r) for r in policy_provider_breakdown_30d]

            policy_rule_breakdown_30d = db.query("""
                SELECT
                  p.rule_type AS label,
                  COUNT(*) AS total,
                  SUM(CASE WHEN e.action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
                  SUM(CASE WHEN e.action = 'kill' THEN 1 ELSE 0 END) AS kill_count
                FROM stream_enforcements e
                JOIN stream_policies p
                  ON p.id = e.policy_id
                WHERE datetime(e.created_at) >= datetime('now', '-30 days')
                GROUP BY p.rule_type
                ORDER BY total DESC, p.rule_type ASC
                LIMIT 10
            """) or []
            policy_rule_breakdown_30d = [dict(r) for r in policy_rule_breakdown_30d]

            policy_top_users_30d = db.query("""
                SELECT
                  label,
                  COUNT(*) AS total,
                  SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
                  SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count
                FROM (
                  SELECT
                    CASE
                      WHEN vu.username IS NOT NULL AND TRIM(vu.username) <> '' THEN vu.username
                      WHEN e.external_user_id IS NOT NULL
                           AND TRIM(e.external_user_id) <> ''
                           AND TRIM(e.external_user_id) NOT GLOB '[0-9]*.[0-9]*.[0-9]*.[0-9]*'
                      THEN e.external_user_id
                      ELSE NULL
                    END AS label,
                    e.action
                  FROM stream_enforcements e
                  LEFT JOIN vodum_users vu
                    ON vu.id = e.vodum_user_id
                  WHERE datetime(e.created_at) >= datetime('now', '-30 days')
                ) q
                WHERE label IS NOT NULL
                GROUP BY label
                ORDER BY total DESC, label ASC
                LIMIT 10
            """) or []
            policy_top_users_30d = [dict(r) for r in policy_top_users_30d]

            policy_recent_enforcements = db.query("""
                SELECT
                  e.created_at,
                  e.action,
                  e.reason,
                  e.provider,
                  p.rule_type,
                  s.name AS server_name,
                  CASE
                    WHEN vu.username IS NOT NULL AND TRIM(vu.username) <> '' THEN vu.username
                    WHEN e.external_user_id IS NOT NULL
                         AND TRIM(e.external_user_id) <> ''
                         AND TRIM(e.external_user_id) NOT GLOB '[0-9]*.[0-9]*.[0-9]*.[0-9]*'
                    THEN e.external_user_id
                    ELSE '—'
                  END AS user_label
                FROM stream_enforcements e
                LEFT JOIN stream_policies p
                  ON p.id = e.policy_id
                LEFT JOIN servers s
                  ON s.id = e.server_id
                LEFT JOIN vodum_users vu
                  ON vu.id = e.vodum_user_id
                ORDER BY e.created_at DESC
                LIMIT 12
            """) or []
            policy_recent_enforcements = [dict(r) for r in policy_recent_enforcements]

            policy_tracked_state = db.query_one("""
                SELECT
                  COUNT(*) AS tracked_1h,
                  SUM(CASE
                        WHEN warned_at IS NOT NULL
                         AND datetime(warned_at) >= datetime('now', '-1 hour')
                        THEN 1 ELSE 0 END) AS warned_1h,
                  SUM(CASE
                        WHEN killed_at IS NOT NULL
                         AND datetime(killed_at) >= datetime('now', '-1 hour')
                        THEN 1 ELSE 0 END) AS killed_1h
                FROM stream_enforcement_state
                WHERE datetime(last_seen_at) >= datetime('now', '-1 hour')
            """) or {}
            policy_tracked_state = dict(policy_tracked_state or {})

            raw_hits_30d = db.query("""
                SELECT
                  date(created_at) AS day,
                  SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
                  SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count,
                  COUNT(*) AS total
                FROM stream_enforcements
                WHERE datetime(created_at) >= datetime('now', '-30 days')
                GROUP BY date(created_at)
                ORDER BY day ASC
            """) or []

            raw_hits_map = {}
            for r in raw_hits_30d:
                rr = dict(r)
                raw_hits_map[rr["day"]] = {
                    "day": rr["day"],
                    "warn_count": int(rr.get("warn_count") or 0),
                    "kill_count": int(rr.get("kill_count") or 0),
                    "total": int(rr.get("total") or 0),
                }

            from datetime import datetime as _dt, timedelta as _td
            today = _dt.utcnow().date()
            policy_hits_30d = []
            for i in range(29, -1, -1):
                d = (today - _td(days=i)).isoformat()
                policy_hits_30d.append(raw_hits_map.get(d, {
                    "day": d,
                    "warn_count": 0,
                    "kill_count": 0,
                    "total": 0,
                }))



        elif tab == "libraries":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            # -------------------------------------------------
            # Filtres TOP PLAYED
            # -------------------------------------------------
            library_range = (request.args.get("lib_range") or "30d").strip().lower()
            if library_range not in ("7d", "30d", "90d", "1y", "all"):
                library_range = "30d"

            library_user = (request.args.get("lib_user") or "all").strip()
            library_user_id = None
            if library_user != "all":
                try:
                    library_user_id = int(library_user)
                except Exception:
                    library_user_id = None
                    library_user = "all"

            # -------------------------------------------------
            # Filtres table
            # -------------------------------------------------
            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "last").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "desc").strip().lower()

            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"

            SORT_MAP = {
                "server": "s.name",
                "library": "l.name",
                "type": "l.type",
                "items": "l.item_count",
                "last": "last_stream_at",
                "plays": "total_plays",
                "duration": "played_ms",
            }

            if sort_key not in SORT_MAP:
                sort_key = "last"

            order_sql = f"{SORT_MAP[sort_key]} {'ASC' if sort_dir == 'asc' else 'DESC'}"

            total = db.query_one(
                """
                WITH plays AS (
                  SELECT
                    h.server_id,
                    CAST(h.library_section_id AS TEXT) AS library_section_id
                  FROM media_session_history h
                  WHERE COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
                  GROUP BY h.server_id, CAST(h.library_section_id AS TEXT)
                )
                SELECT COUNT(*) AS cnt
                FROM libraries l
                JOIN plays p
                  ON p.server_id = l.server_id
                 AND p.library_section_id = CAST(l.section_id AS TEXT)
                """
            ) or {"cnt": 0}
            total = dict(total) if total else {"cnt": 0}

            rows = db.query(
                f"""
                WITH plays AS (
                  SELECT
                    h.server_id,
                    CAST(h.library_section_id AS TEXT) AS library_section_id,
                    MAX(h.stopped_at) AS stopped_at,
                    (
                      CAST(h.server_id AS TEXT) || '|' ||
                      CAST(h.media_user_id AS TEXT) || '|' ||
                      COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                      strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key,
                    MAX(
                      MIN(
                        COALESCE(h.watch_ms, 0),
                        CASE
                          WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                          ELSE COALESCE(h.watch_ms, 0)
                        END
                      )
                    ) AS watch_ms
                  FROM media_session_history h
                  WHERE COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
                  GROUP BY
                    h.server_id,
                    CAST(h.library_section_id AS TEXT),
                    (
                      CAST(h.server_id AS TEXT) || '|' ||
                      CAST(h.media_user_id AS TEXT) || '|' ||
                      COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                      strftime('%Y-%m-%d %H:%M', h.started_at)
                    )
                ),
                lib_stats AS (
                  SELECT
                    server_id,
                    library_section_id,
                    MAX(stopped_at) AS last_stream_at,
                    COUNT(*) AS total_plays,
                    COALESCE(SUM(watch_ms), 0) AS played_ms
                  FROM plays
                  GROUP BY server_id, library_section_id
                )
                SELECT
                  l.id AS library_id,
                  l.section_id AS library_section_id,
                  l.name AS library_name,
                  s.id AS server_id,
                  s.name AS server_name,
                  s.type AS provider,
                  l.type AS media_type,
                  l.item_count AS item_count,
                  ls.last_stream_at,
                  ls.total_plays,
                  ls.played_ms
                FROM libraries l
                JOIN servers s ON s.id = l.server_id
                JOIN lib_stats ls
                  ON ls.server_id = l.server_id
                 AND ls.library_section_id = CAST(l.section_id AS TEXT)
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                (offset,),
            )

            rows = [dict(r) for r in rows]
            hidden_libraries_count = 0

            rows = [dict(r) for r in rows]
            hidden_libraries_count = 0

            for r in rows:
                ms = r.get("played_ms") or 0
                r["played_duration"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"
                r["has_last_stream"] = True

            total_rows = int(total.get("cnt") or 0)
            total_pages = max(1, (total_rows + per_page - 1) // per_page)

            def build_url(p):
                args = dict(request.args)
                args["tab"] = "libraries"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = {
                "page": page,
                "total_pages": total_pages,
                "total_rows": total_rows,
                "first_url": build_url(1),
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
                "last_url": build_url(total_pages),
            }

            # -------------------------------------------------
            # Liste users pour filtre du top played
            # On filtre sur le user VODUM de référence, pas sur media_users
            # -------------------------------------------------
            library_users = db.query(
                """
                SELECT DISTINCT
                  vu.id,
                  COALESCE(
                    NULLIF(TRIM(vu.username), ''),
                    NULLIF(TRIM(vu.email), ''),
                    'User #' || vu.id
                  ) AS label
                FROM media_session_history h
                JOIN media_users mu ON mu.id = h.media_user_id
                JOIN vodum_users vu ON vu.id = mu.vodum_user_id
                ORDER BY label COLLATE NOCASE
                """
            )
            library_users = [dict(u) for u in (library_users or [])]

            # -------------------------------------------------
            # TOP PLAYED PAR LIBRARY
            # -------------------------------------------------
            range_to_sql = {
                "7d": "-7 days",
                "30d": "-30 days",
                "90d": "-90 days",
                "1y": "-1 year",
            }

            where_hist = ["1=1"]
            params_hist = []

            if library_range != "all":
                where_hist.append("h.stopped_at >= datetime('now', ?)")
                params_hist.append(range_to_sql[library_range])

            if library_user_id is not None:
                where_hist.append("vu_ref.id = ?")
                params_hist.append(library_user_id)

            where_hist_sql = " AND ".join(where_hist)

            top_rows = db.query(
                f"""
                WITH hist AS (
                  SELECT
                    h.id AS hist_id,
                    l.id AS library_id,
                    l.name AS library_name,
                    l.type AS media_type,
                    s.id AS server_id,
                    s.name AS server_name,
                    s.type AS provider,
                    vu_ref.id AS vodum_user_id,
                    h.media_user_id,
                    h.media_key,
                    h.raw_json,
                    h.stopped_at,
                    h.started_at,
                    CAST(h.library_section_id AS TEXT) AS history_library_section_id,
                    LOWER(TRIM(COALESCE(h.media_type, ''))) AS history_media_type,

                    CASE
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                        THEN TRIM(h.grandparent_title)
                      ELSE TRIM(COALESCE(h.title, 'Unknown'))
                    END AS display_title,

                    CASE
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                        THEN 'series:' || LOWER(TRIM(h.grandparent_title))
                      WHEN NULLIF(TRIM(h.media_key), '') IS NOT NULL
                        THEN 'media:' || TRIM(h.media_key)
                      ELSE 'title:' || LOWER(TRIM(COALESCE(h.title, 'Unknown')))
                    END AS media_group_key,

                    (
                      CAST(h.server_id AS TEXT) || '|' ||
                      CAST(h.library_section_id AS TEXT) || '|' ||
                      CAST(vu_ref.id AS TEXT) || '|' ||
                      COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                      strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key

                  FROM media_session_history h
                  JOIN libraries l
                    ON l.server_id = h.server_id
                   AND CAST(l.section_id AS TEXT) = CAST(h.library_section_id AS TEXT)
                  JOIN servers s
                    ON s.id = l.server_id
                  JOIN media_users mu_ref
                    ON mu_ref.id = h.media_user_id
                  JOIN vodum_users vu_ref
                    ON vu_ref.id = mu_ref.vodum_user_id
                  WHERE {where_hist_sql}
                    AND COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(library_id) AS library_id,
                    MAX(library_name) AS library_name,
                    MAX(media_type) AS media_type,
                    MAX(server_id) AS server_id,
                    MAX(server_name) AS server_name,
                    MAX(provider) AS provider,
                    MAX(vodum_user_id) AS vodum_user_id,
                    MAX(media_key) AS media_key,
                    MAX(display_title) AS display_title,
                    MAX(media_group_key) AS media_group_key,
                    MAX(stopped_at) AS stopped_at
                  FROM hist
                  GROUP BY play_key
                ),
                media_agg AS (
                  SELECT
                    library_id,
                    library_name,
                    media_type,
                    server_id,
                    server_name,
                    provider,
                    media_group_key,
                    MAX(display_title) AS display_title,
                    MAX(media_key) AS media_key,
                    COUNT(*) AS plays,
                    COUNT(DISTINCT vodum_user_id) AS user_count,
                    MAX(stopped_at) AS last_play_at
                  FROM plays
                  GROUP BY
                    library_id,
                    library_name,
                    media_type,
                    server_id,
                    server_name,
                    provider,
                    media_group_key
                ),
                latest_snapshots AS (
                  SELECT
                    library_id,
                    media_group_key,
                    raw_json,
                    ROW_NUMBER() OVER (
                      PARTITION BY library_id, media_group_key
                      ORDER BY stopped_at DESC, hist_id DESC
                    ) AS rn
                  FROM hist
                ),
                ranked AS (
                  SELECT
                    m.*,
                    ls.raw_json,
                    ROW_NUMBER() OVER (
                      PARTITION BY m.library_id
                      ORDER BY m.plays DESC, m.user_count DESC, m.last_play_at DESC, m.display_title ASC
                    ) AS row_in_library
                  FROM media_agg m
                  LEFT JOIN latest_snapshots ls
                    ON ls.library_id = m.library_id
                   AND ls.media_group_key = m.media_group_key
                   AND ls.rn = 1
                )
                SELECT
                  library_id,
                  library_name,
                  media_type,
                  server_id,
                  server_name,
                  provider,
                  media_group_key,
                  display_title,
                  media_key,
                  plays,
                  user_count,
                  last_play_at,
                  raw_json,
                  row_in_library
                FROM ranked
                WHERE row_in_library <= 6
                ORDER BY library_name COLLATE NOCASE, row_in_library ASC
                """,
                tuple(params_hist),
            )

            top_rows = [dict(r) for r in (top_rows or [])]

            cards_by_library = {}
            for r in top_rows:
                card = cards_by_library.get(r["library_id"])
                if not card:
                    card = {
                        "library_id": r["library_id"],
                        "library_name": r["library_name"],
                        "server_name": r["server_name"],
                        "media_type": r.get("media_type"),
                        "items": [],
                        "total_plays": 0,
                        "total_users": 0,
                    }
                    cards_by_library[r["library_id"]] = card

                item = dict(r)
                item["poster_url"] = _build_history_poster_url(item)

                card["items"].append(item)
                card["total_plays"] += int(item.get("plays") or 0)

            library_top_cards = list(cards_by_library.values())

            for card in library_top_cards:
                users_seen = set()
                for item in card["items"]:
                    try:
                        users_seen.add(int(item.get("user_count") or 0))
                    except Exception:
                        pass
                card["total_users"] = sum(int(x.get("user_count") or 0) for x in card["items"])

            library_top_cards.sort(
                key=lambda c: (
                    -(c.get("total_plays") or 0),
                    str(c.get("library_name") or "").lower(),
                )
            )

        # --------------------------
        # Servers tab (stats combinées + par serveur + tops + breakdowns)
        # --------------------------
        server_range = request.args.get("range", "7d")

        servers_combined = None
        servers_details = None
        servers_sessions_day = None
        servers_media_types = None
        servers_clients = None
        servers_top_users = None
        servers_top_titles = None
        servers_unique_ips = None

        if tab == "servers":
            # Range filter basé sur stopped_at (stats "terminées" fiables)
            if server_range == "all":
                where_hist = "1=1"
                params_hist = ()
            else:
                delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(server_range, "-7 days")
                where_hist = "stopped_at >= datetime('now', ?)"
                params_hist = (delta,)

            # Global (tous serveurs)
            servers_combined = db.query_one(
                f"""
                WITH base AS (
                  SELECT
                    server_id,
                    media_user_id,
                    started_at,
                    stopped_at,
                    media_key,
                    was_transcode,
                    peak_bitrate,
                    ip,
                    MIN(
                      COALESCE(watch_ms, 0),
                      CASE
                        WHEN COALESCE(duration_ms, 0) > 0 THEN duration_ms
                        ELSE COALESCE(watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(server_id AS TEXT) || '|' ||
                     CAST(media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', started_at)
                    ) AS play_key
                  FROM media_session_history
                  WHERE {where_hist}
                ),
                hist AS (
                  SELECT
                    MAX(server_id) AS server_id,
                    MAX(media_user_id) AS media_user_id,
                    MAX(stopped_at) AS stopped_at,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(was_transcode) AS was_transcode,
                    MAX(peak_bitrate) AS peak_bitrate,
                    MAX(ip) AS ip
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  COUNT(*) AS sessions,
                  COUNT(DISTINCT media_user_id) AS active_users,
                  COALESCE(SUM(watch_ms), 0) AS watch_ms,
                  SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes,
                  AVG(NULLIF(peak_bitrate, 0)) AS avg_peak_bitrate,
                  MAX(peak_bitrate) AS max_peak_bitrate,
                  COUNT(DISTINCT ip) AS unique_ips
                FROM hist
                """,
                params_hist,
            ) or {}
            servers_combined = dict(servers_combined)

            # Détails par serveur (hist + live)
            params = tuple(params_hist) + (live_window_sql,)
            servers_details = db.query(
                f"""
                WITH base AS (
                  SELECT
                    *,
                    MIN(
                      COALESCE(watch_ms, 0),
                      CASE
                        WHEN COALESCE(duration_ms, 0) > 0 THEN duration_ms
                        ELSE COALESCE(watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(server_id AS TEXT) || '|' ||
                     CAST(media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', started_at)
                    ) AS play_key
                  FROM media_session_history
                  WHERE {where_hist}
                ),
                hist AS (
                  SELECT
                    MAX(server_id) AS server_id,
                    MAX(media_user_id) AS media_user_id,
                    MAX(stopped_at) AS stopped_at,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(was_transcode) AS was_transcode,
                    MAX(peak_bitrate) AS peak_bitrate,
                    MAX(ip) AS ip
                  FROM base
                  GROUP BY play_key
                ),
                live AS (
                  SELECT * FROM media_sessions
                  WHERE datetime(last_seen_at) >= datetime('now', ?)
                )
                SELECT
                  s.id AS server_id,
                  s.name,
                  s.type,
                  s.status,
                  s.last_checked,

                  (SELECT COUNT(*) FROM libraries l WHERE l.server_id = s.id) AS libraries,
                  (SELECT COUNT(*) FROM media_users mu WHERE mu.server_id = s.id) AS users,

                  (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id) AS live_sessions,
                  (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id AND x.is_transcode = 1) AS live_transcodes,

                  (SELECT COUNT(*) FROM hist h WHERE h.server_id = s.id) AS sessions,
                  (SELECT COUNT(DISTINCT h.media_user_id) FROM hist h WHERE h.server_id = s.id) AS active_users,
                  (SELECT COALESCE(SUM(h.watch_ms), 0) FROM hist h WHERE h.server_id = s.id) AS watch_ms,
                  (SELECT SUM(CASE WHEN h.was_transcode = 1 THEN 1 ELSE 0 END) FROM hist h WHERE h.server_id = s.id) AS transcodes,
                  (SELECT AVG(NULLIF(h.peak_bitrate, 0)) FROM hist h WHERE h.server_id = s.id) AS avg_peak_bitrate,
                  (SELECT MAX(h.peak_bitrate) FROM hist h WHERE h.server_id = s.id) AS max_peak_bitrate,
                  (SELECT COUNT(DISTINCT h.ip) FROM hist h WHERE h.server_id = s.id) AS unique_ips

                FROM servers s
                WHERE s.type IN ('plex','jellyfin')
                ORDER BY s.type, s.name
                """,
                params,
            )
            servers_details = [dict(r) for r in servers_details]
            _apply_server_resource_stats(servers_details, server_resource_stats)

            # Courbe sessions/jour par serveur (multi-datasets côté front)
            servers_sessions_day = db.query(
                f"""
                WITH base AS (
                  SELECT
                    server_id,
                    started_at,
                    stopped_at,
                    media_key,
                    (CAST(server_id AS TEXT) || '|' ||
                     CAST(media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', started_at)
                    ) AS play_key
                  FROM media_session_history
                  WHERE {where_hist}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(stopped_at) AS stopped_at
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  date(stopped_at) AS day,
                  server_id,
                  COUNT(*) AS sessions
                FROM plays
                GROUP BY day, server_id
                ORDER BY day ASC
                """,
                params_hist,
            )
            servers_sessions_day = [dict(r) for r in servers_sessions_day]

            # Répartition media_type par serveur (normalisé pour UI)
            servers_media_types = db.query(
                f"""
                WITH base AS (
                  SELECT
                    server_id,
                    started_at,
                    media_key,

                    CASE
                      -- Priorité au grandparent_title : très fiable pour les épisodes Plex
                      WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 'serie'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'serie'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 'movie'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                      ELSE 'other'
                    END AS media_type,

                    CASE
                      WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 400
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 400
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 300
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 200
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 100
                      ELSE 0
                    END AS media_rank,

                    MIN(
                      COALESCE(watch_ms, 0),
                      CASE
                        WHEN COALESCE(duration_ms, 0) > 0 THEN duration_ms
                        ELSE COALESCE(watch_ms, 0)
                      END
                    ) AS watch_ms_capped,

                    (CAST(server_id AS TEXT) || '|' ||
                     CAST(media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', started_at)
                    ) AS play_key
                  FROM media_session_history
                  WHERE {where_hist}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    CASE MAX(media_rank)
                      WHEN 400 THEN 'serie'
                      WHEN 300 THEN 'movie'
                      WHEN 200 THEN 'music'
                      WHEN 100 THEN 'photo'
                      ELSE 'other'
                    END AS media_type,
                    MAX(watch_ms_capped) AS watch_ms
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  server_id,
                  media_type,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms),0) AS watch_ms
                FROM plays
                GROUP BY server_id, media_type
                ORDER BY server_id, sessions DESC
                """,
                params_hist,
            )
            servers_media_types = [dict(r) for r in servers_media_types]



            # Top clients / devices (global + par serveur)
            servers_clients = db.query(
                f"""
                WITH base AS (
                  SELECT
                    h.server_id,
                    s.name AS server_name,
                    COALESCE(h.client_product, COALESCE(h.device, 'unknown')) AS client,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    h.was_transcode,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     CAST(h.media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  JOIN servers s ON s.id = h.server_id
                  WHERE {where_hist}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(server_name) AS server_name,
                    MAX(client) AS client,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(was_transcode) AS was_transcode
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  server_id,
                  server_name,
                  client,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms),0) AS watch_ms,
                  SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM plays
                GROUP BY server_id, server_name, client
                ORDER BY sessions DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_clients = [dict(r) for r in servers_clients]

            # Top users (global + par serveur)
            servers_top_users = db.query(
                f"""
                WITH base AS (
                  SELECT
                    h.server_id,
                    s.name AS server_name,
                    h.media_user_id,
                    COALESCE(mu.username, mu.email, 'User #' || h.media_user_id) AS user_label,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    h.was_transcode,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     CAST(h.media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  JOIN servers s ON s.id = h.server_id
                  LEFT JOIN media_users mu ON mu.id = h.media_user_id
                  WHERE {where_hist}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(server_name) AS server_name,
                    MAX(media_user_id) AS media_user_id,
                    MAX(user_label) AS user_label,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(was_transcode) AS was_transcode
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  server_id,
                  server_name,
                  media_user_id,
                  user_label,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms),0) AS watch_ms,
                  SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM plays
                GROUP BY server_id, server_name, media_user_id
                ORDER BY watch_ms DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_top_users = [dict(r) for r in servers_top_users]

            # Top contenus (global + par serveur)
            servers_top_titles = db.query(
                f"""
                WITH base AS (
                  SELECT
                    h.server_id,
                    s.name AS server_name,
                    TRIM(
                      COALESCE(h.grandparent_title || ' - ', '') ||
                      COALESCE(h.parent_title || ' - ', '') ||
                      COALESCE(h.title, 'Unknown')
                    ) AS full_title,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    h.was_transcode,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     CAST(h.media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  JOIN servers s ON s.id = h.server_id
                  WHERE {where_hist}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(server_name) AS server_name,
                    MAX(full_title) AS full_title,
                    MAX(watch_ms_capped) AS watch_ms,
                    MAX(was_transcode) AS was_transcode
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  server_id,
                  server_name,
                  full_title,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms),0) AS watch_ms,
                  SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM plays
                GROUP BY server_id, server_name, full_title
                ORDER BY watch_ms DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_top_titles = [dict(r) for r in servers_top_titles]

            # IPs uniques (par serveur + global, plus “top IP”)
            servers_unique_ips = db.query(
                f"""
                WITH base AS (
                  SELECT
                    h.server_id,
                    s.name AS server_name,
                    h.ip,
                    MIN(
                      COALESCE(h.watch_ms, 0),
                      CASE
                        WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                        ELSE COALESCE(h.watch_ms, 0)
                      END
                    ) AS watch_ms_capped,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     CAST(h.media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  JOIN servers s ON s.id = h.server_id
                  WHERE {where_hist}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(server_id) AS server_id,
                    MAX(server_name) AS server_name,
                    MAX(ip) AS ip,
                    MAX(watch_ms_capped) AS watch_ms
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  server_id,
                  server_name,
                  ip,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms),0) AS watch_ms
                FROM plays
                GROUP BY server_id, server_name, ip
                ORDER BY sessions DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_unique_ips = [dict(r) for r in servers_unique_ips]




        # ------------------------------------------------------------------
        # HTMX: si requête dynamique, on renvoie uniquement le contenu de l’onglet
        # ------------------------------------------------------------------
        is_hx = bool(request.headers.get("HX-Request"))
        if is_hx:
            tab_tpl = {
                "overview": "monitoring/overview_body.html",
                "now_playing": "monitoring/tabs/now_playing.html",
                "policies": "monitoring/tabs/policies.html",
                "activity": "monitoring/tabs/activity.html",
                "history": "monitoring/tabs/history.html",
                "libraries": "monitoring/tabs/libraries.html",
                "users": "monitoring/tabs/users.html",
                "servers": "monitoring/tabs/servers.html",
            }.get(tab, "monitoring/overview_body.html")

            resp = make_response(render_template(
                tab_tpl,
                active_page="monitoring",
                tab=tab,
                servers=servers,
                configured_server_count=configured_server_count,
                server_stats=server_stats,
                sessions_stats=sessions_stats,
                live_servers=live_servers,
                sessions=sessions,
                events=events,
                live_window_seconds=live_window_seconds,
                stats_7d=stats_7d,
                top_users_30d=top_users_30d,
                top_content_30d=top_content_30d,
                top_movies_30d=top_movies_30d,
                concurrent_7d=concurrent_7d,
                rows=rows,
                filters=filters,
                pagination=pagination,
                sort_key=sort_key,
                sort_dir=sort_dir,
                policies=policies,
                edit_policy=locals().get('edit_policy'),
                server_range=server_range,
                servers_combined=servers_combined,
                servers_details=servers_details,
                servers_sessions_day=servers_sessions_day,
                servers_media_types=servers_media_types,
                servers_clients=servers_clients,
                servers_top_users=servers_top_users,
                servers_top_titles=servers_top_titles,
                servers_unique_ips=servers_unique_ips,
                library_top_cards=library_top_cards,
                library_users=library_users,
                library_range=library_range,
                library_user=library_user,
                hidden_libraries_count=hidden_libraries_count,
                policy_dashboard=policy_dashboard,
                policy_hits_30d=policy_hits_30d,
                policy_rule_breakdown_30d=policy_rule_breakdown_30d,
                policy_provider_breakdown_30d=policy_provider_breakdown_30d,
                policy_scope_breakdown=policy_scope_breakdown,
                policy_top_users_30d=policy_top_users_30d,
                policy_recent_enforcements=policy_recent_enforcements,
                policy_tracked_state=policy_tracked_state,
            ))
            if sort_key and sort_dir:
                resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
                resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)

            return resp

        # Page complète (chargement normal)
        resp = make_response(render_template(
            "monitoring/monitoring.html",
            active_page="monitoring",
            tab=tab,
            servers=servers,
            configured_server_count=configured_server_count,
            server_stats=server_stats,
            sessions_stats=sessions_stats,
            live_servers=live_servers,
            sessions=sessions,
            events=events,
            live_window_seconds=live_window_seconds,
            stats_7d=stats_7d,
            top_users_30d=top_users_30d,
            top_content_30d=top_content_30d,
            top_movies_30d=top_movies_30d,
            concurrent_7d=concurrent_7d,
            rows=rows,
            filters=filters,
            pagination=pagination,
            sort_key=sort_key,
            sort_dir=sort_dir,
            policies=policies,
            edit_policy=locals().get('edit_policy'),
            server_range=server_range,
            servers_combined=servers_combined,
            servers_details=servers_details,
            servers_sessions_day=servers_sessions_day,
            servers_media_types=servers_media_types,
            servers_clients=servers_clients,
            servers_top_users=servers_top_users,
            servers_top_titles=servers_top_titles,
            servers_unique_ips=servers_unique_ips,
            library_top_cards=library_top_cards,
            library_users=library_users,
            library_range=library_range,
            library_user=library_user,
            hidden_libraries_count=hidden_libraries_count,
            policy_dashboard=policy_dashboard,
            policy_hits_30d=policy_hits_30d,
            policy_rule_breakdown_30d=policy_rule_breakdown_30d,
            policy_provider_breakdown_30d=policy_provider_breakdown_30d,
            policy_scope_breakdown=policy_scope_breakdown,
            policy_top_users_30d=policy_top_users_30d,
            policy_recent_enforcements=policy_recent_enforcements,
            policy_tracked_state=policy_tracked_state,
        ))
        
        if sort_key and sort_dir:
            resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
            resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)
        return resp



