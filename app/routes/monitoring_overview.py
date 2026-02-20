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
            SELECT id, name, type, url, local_url, public_url, status, last_checked
            FROM servers
            WHERE type IN ('plex','jellyfin')
            ORDER BY type, name
            """
        )

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

        # --------------------------
        # Sessions live (overview)
        # --------------------------
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
        
        # --------------------------
        # Snapshot "à l'affichage" (garantit que le peak ne redescend pas)
        # On limite à 1 insert / 30s pour éviter de spammer la DB si tu refresh souvent.
        # --------------------------
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

            # purge (garde 30 jours)
            db.execute("DELETE FROM monitoring_snapshots WHERE ts < datetime('now','-30 days')")
        except Exception as e:
            logger.warning(f"Could not write monitoring snapshot (overview): {e}")

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

        # ------------------------------------------------------------------
        # Enrich Now Playing: SxxExx + jaquette (sans changer la DB)
        # ------------------------------------------------------------------
        def _safe_int(v):
            try:
                if v is None:
                    return None
                return int(v)
            except Exception:
                return None

        sessions = [dict(r) for r in sessions]

        for s in sessions:
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

            # ---------- PLEX ----------
            if provider == "plex":
                attrs = (data.get("VideoOrTrack") or {})

                # Episode numbers (Plex XML attribs are stored in raw_json)
                # parentIndex = season number, index = episode number
                season = _safe_int(attrs.get("parentIndex"))
                episode = _safe_int(attrs.get("index"))

                s["season_number"] = season
                s["episode_number"] = episode

                if season is not None and episode is not None:
                    s["episode_code"] = f"S{season:02d}E{episode:02d}"
                elif season is not None:
                    s["episode_code"] = f"S{season}"

                # Poster path preference for series:
                # grandparentThumb (show poster) > parentThumb (season poster) > thumb (item)
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

            # ---------- JELLYFIN ----------
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

                # Poster: for episodes, prefer SeriesId (show poster). fallback to item Id.
                poster_item_id = now.get("SeriesId") or now.get("Id") or s.get("media_key")
                if poster_item_id:
                    s["poster_url"] = url_for(
                        "api_monitoring_poster",
                        server_id=s["server_id"],
                        item_id=str(poster_item_id),
                    )


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
        # Stats 7d + tops
        # --------------------------
        stats_7d = db.query_one(
                            """
                            SELECT
                              COUNT(DISTINCT
                                CAST(h.server_id AS TEXT) || '|' ||
                                COALESCE(CAST(h.media_user_id AS TEXT), '') || '|' ||
                                COALESCE(h.started_at, '') || '|' ||
                                COALESCE(h.media_key, '') || '|' ||
                                COALESCE(h.client_name, '')
                              ) AS sessions,

                              -- Active users (7d) = VODUM users distincts (merge inclus)
                              -- Si un media_user n'est pas mergé, on le compte quand même comme un user unique.
                              COUNT(DISTINCT COALESCE(
                                CAST(mu.vodum_user_id AS TEXT),
                                'media:' || CAST(mu.id AS TEXT)
                              )) AS active_users,

                              SUM(h.watch_ms) AS total_watch_ms,
                              AVG(CASE WHEN h.watch_ms > 0 THEN h.watch_ms END) AS avg_watch_ms
                            FROM media_session_history h
                            LEFT JOIN media_users mu ON mu.id = h.media_user_id
                            WHERE h.started_at >= datetime('now', '-7 days')
                            """
                        ) or {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
        stats_7d = dict(stats_7d) if stats_7d else {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}

        top_users_30d = db.query(
            """
            SELECT
              mu.username,
              COUNT(*) AS sessions,
              SUM(h.watch_ms) AS watch_ms
            FROM media_session_history h
            LEFT JOIN media_users mu ON mu.id = h.media_user_id
            WHERE h.started_at >= datetime('now', '-30 days')
            GROUP BY h.media_user_id
            ORDER BY watch_ms DESC
            LIMIT 10
            """
        )

        top_content_30d = db.query(
            """
            SELECT
              COALESCE(title, '-') AS title,
              COALESCE(grandparent_title, '') AS grandparent_title,
              COUNT(*) AS sessions,
              SUM(watch_ms) AS watch_ms
            FROM media_session_history
            WHERE started_at >= datetime('now', '-30 days')
            GROUP BY title, grandparent_title
            ORDER BY watch_ms DESC
            LIMIT 10
            """
        )


        # --------------------------
        # Peak streams (7d) = max de Live sessions (snapshots)
        # --------------------------
        concurrent_7d = db.query_one(
            """
            SELECT COALESCE(MAX(live_sessions), 0) AS peak_streams
            FROM monitoring_snapshots
            WHERE ts >= datetime('now', '-7 days')
            """
        ) or {"peak_streams": 0}
        concurrent_7d = dict(concurrent_7d) if concurrent_7d else {"peak_streams": 0}

        # Sécurité UX : peak >= streams live actuels
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
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
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
            # Total rows (avec filtre username)
            # --------------------------
            if q:
                like = f"%{q}%"
                total = db.query_one(
                    """
                    WITH users_with_hist AS (
                      SELECT DISTINCT media_user_id AS uid
                      FROM media_session_history
                      WHERE media_user_id IS NOT NULL
                    )
                    SELECT COUNT(*) AS cnt
                    FROM media_users mu
                    JOIN users_with_hist u ON u.uid = mu.id
                    LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
                    WHERE (
                      COALESCE(mu.username,'') LIKE ? OR
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
                    h.media_user_id,
                    h.stopped_at,
                    h.watch_ms,
                    h.ip,
                    h.device,
                    h.client_name,
                    h.client_product,
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
                agg AS (
                  SELECT
                    group_key,
                    MAX(stopped_at) AS last_watch_at,
                    COUNT(*) AS total_plays,
                    COALESCE(SUM(watch_ms),0) AS watch_ms
                  FROM base
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
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
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
            # Parse rule JSON + detect system-managed policies
            for p in policies:
                try:
                    p["_rule"] = json.loads(p.get("rule_value_json") or "{}")
                except Exception:
                    p["_rule"] = {}
                p["_is_system"] = bool(p["_rule"].get("system_tag"))

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



        elif tab == "libraries":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            total = db.query_one("SELECT COUNT(*) AS cnt FROM libraries") or {"cnt": 0}
            total = dict(total) if total else {"cnt": 0}

            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "last").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "asc").strip().lower()

            if sort_dir not in ("asc", "desc"):
                sort_dir = "asc"

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
                sort_key = "server"

            order_sql = f"{SORT_MAP[sort_key]} {'ASC' if sort_dir == 'asc' else 'DESC'}"

            rows = db.query(
                f"""
                SELECT
                  l.name AS library_name,
                  s.name AS server_name,
                  l.type AS media_type,

                  l.item_count AS item_count,

                  (
                    SELECT MAX(h.stopped_at)
                    FROM media_session_history h
                    WHERE h.server_id = l.server_id
                      AND h.library_section_id = l.section_id
                  ) AS last_stream_at,

                  (
                    SELECT COUNT(*)
                    FROM media_session_history h
                    WHERE h.server_id = l.server_id
                      AND h.library_section_id = l.section_id
                  ) AS total_plays,

                  (
                    SELECT COALESCE(SUM(h.watch_ms), 0)
                    FROM media_session_history h
                    WHERE h.server_id = l.server_id
                      AND h.library_section_id = l.section_id
                  ) AS played_ms

                FROM libraries l
                JOIN servers s ON s.id = l.server_id
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                (offset,),
            )


            rows = [dict(r) for r in rows]
            for r in rows:
                ms = r.get("played_ms") or 0
                r["played_duration"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"

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
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
            }

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
                SELECT
                  COUNT(*) AS sessions,
                  COUNT(DISTINCT media_user_id) AS active_users,
                  COALESCE(SUM(watch_ms), 0) AS watch_ms,
                  SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes,
                  AVG(NULLIF(peak_bitrate, 0)) AS avg_peak_bitrate,
                  MAX(peak_bitrate) AS max_peak_bitrate,
                  COUNT(DISTINCT ip) AS unique_ips
                FROM media_session_history
                WHERE {where_hist}
                """,
                params_hist,
            ) or {}
            servers_combined = dict(servers_combined)

            # Détails par serveur (hist + live)
            params = tuple(params_hist) + (live_window_sql,)
            servers_details = db.query(
                f"""
                WITH hist AS (
                  SELECT * FROM media_session_history
                  WHERE {where_hist}
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

            # Courbe sessions/jour par serveur (multi-datasets côté front)
            servers_sessions_day = db.query(
                f"""
                SELECT
                  date(stopped_at) AS day,
                  server_id,
                  COUNT(*) AS sessions
                FROM media_session_history
                WHERE {where_hist}
                GROUP BY day, server_id
                ORDER BY day ASC
                """,
                params_hist,
            )
            servers_sessions_day = [dict(r) for r in servers_sessions_day]

            # Répartition media_type par serveur (normalisé pour UI)
            servers_media_types = db.query(
                f"""
                SELECT
                  server_id,
                  CASE
                    WHEN LOWER(COALESCE(media_type,'')) IN ('movie', 'film') THEN 'movie'
                    WHEN LOWER(COALESCE(media_type,'')) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'serie'
                    WHEN LOWER(COALESCE(media_type,'')) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                    WHEN LOWER(COALESCE(media_type,'')) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                    ELSE 'other'
                  END AS media_type,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms),0) AS watch_ms
                FROM media_session_history
                WHERE {where_hist}
                GROUP BY server_id, media_type
                ORDER BY server_id, sessions DESC
                """,
                params_hist,
            )
            servers_media_types = [dict(r) for r in servers_media_types]



            # Top clients / devices (global + par serveur)
            servers_clients = db.query(
                f"""
                SELECT
                  h.server_id,
                  s.name AS server_name,
                  COALESCE(h.client_product, COALESCE(h.device, 'unknown')) AS client,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(h.watch_ms),0) AS watch_ms,
                  SUM(CASE WHEN h.was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM media_session_history h
                JOIN servers s
                  ON s.id = h.server_id
                WHERE {where_hist}
                GROUP BY h.server_id, s.name, client
                ORDER BY sessions DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_clients = [dict(r) for r in servers_clients]

            # Top users (global + par serveur)
            servers_top_users = db.query(
                f"""
                SELECT
                  h.server_id,
                  s.name AS server_name,
                  h.media_user_id,
                  COALESCE(mu.username, mu.email, 'User #' || h.media_user_id) AS user_label,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(h.watch_ms),0) AS watch_ms,
                  SUM(CASE WHEN h.was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM media_session_history h
                JOIN servers s
                  ON s.id = h.server_id
                LEFT JOIN media_users mu
                  ON mu.id = h.media_user_id
                WHERE {where_hist}
                GROUP BY h.server_id, s.name, h.media_user_id
                ORDER BY watch_ms DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_top_users = [dict(r) for r in servers_top_users]

            # Top contenus (global + par serveur)
            servers_top_titles = db.query(
                f"""
                SELECT
                  h.server_id,
                  s.name AS server_name,
                  TRIM(
                    COALESCE(h.grandparent_title || ' - ', '') ||
                    COALESCE(h.parent_title || ' - ', '') ||
                    COALESCE(h.title, 'Unknown')
                  ) AS full_title,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(h.watch_ms),0) AS watch_ms,
                  SUM(CASE WHEN h.was_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
                FROM media_session_history h
                JOIN servers s
                  ON s.id = h.server_id
                WHERE {where_hist}
                GROUP BY h.server_id, s.name, full_title
                ORDER BY watch_ms DESC
                LIMIT 200
                """,
                params_hist,
            )
            servers_top_titles = [dict(r) for r in servers_top_titles]

            # IPs uniques (par serveur + global, plus “top IP”)
            servers_unique_ips = db.query(
                f"""
                SELECT
                  h.server_id,
                  s.name AS server_name,
                  h.ip,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(h.watch_ms),0) AS watch_ms
                FROM media_session_history h
                JOIN servers s
                  ON s.id = h.server_id
                WHERE {where_hist}
                GROUP BY h.server_id, s.name, h.ip
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
                server_stats=server_stats,
                sessions_stats=sessions_stats,
                sessions=sessions,
                events=events,
                live_window_seconds=live_window_seconds,
                stats_7d=stats_7d,
                top_users_30d=top_users_30d,
                top_content_30d=top_content_30d,
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
            server_stats=server_stats,
            sessions_stats=sessions_stats,
            sessions=sessions,
            events=events,
            live_window_seconds=live_window_seconds,
            stats_7d=stats_7d,
            top_users_30d=top_users_30d,
            top_content_30d=top_content_30d,
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
        ))
        
        if sort_key and sort_dir:
            resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
            resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)
        return resp



