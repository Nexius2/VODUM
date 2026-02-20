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



def json_rows(rows):
    return current_app.response_class(
        json.dumps([dict(r) for r in rows], ensure_ascii=False),
        mimetype='application/json',
    )

def register(app):
    @app.route("/api/monitoring/poster/<int:server_id>")
    def api_monitoring_poster(server_id: int):
        db = get_db()
        srv = db.query_one(
            """
            SELECT id, type, url, local_url, public_url, token
            FROM servers
            WHERE id = ?
              AND type IN ('plex','jellyfin')
            LIMIT 1
            """,
            (server_id,),
        )
        if not srv:
            abort(404)

        srv = dict(srv)
        stype = (srv.get("type") or "").lower()
        token = srv.get("token")
        if not token:
            abort(404)

        # url > local_url > public_url
        bases = []
        for u in (srv.get("url"), srv.get("local_url"), srv.get("public_url")):
            if u and str(u).strip():
                b = str(u).strip().rstrip("/")
                if b not in bases:
                    bases.append(b)

        if not bases:
            abort(502)

        def _try_get(full_url, headers=None, params=None):
            r = requests.get(full_url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            return r

        # ---------------- PLEX ----------------
        if stype == "plex":
            path = request.args.get("path")
            if not path:
                abort(400)

            if not path.startswith("/"):
                path = "/" + path

            params = {"X-Plex-Token": token}

            last_err = None
            for base in bases:
                try:
                    r = _try_get(base + path, params=params)
                    ct = r.headers.get("Content-Type") or "image/jpeg"
                    return Response(
                        r.content,
                        mimetype=ct,
                        headers={"Cache-Control": "public, max-age=300"},
                    )
                except Exception as e:
                    last_err = e
                    continue

            abort(502)

        # --------------- JELLYFIN --------------
        if stype == "jellyfin":
            item_id = request.args.get("item_id")
            if not item_id:
                abort(400)

            # small poster size by default
            w = request.args.get("w", "120")
            q = request.args.get("q", "90")

            path = f"/Items/{item_id}/Images/Primary"
            params = {"maxWidth": w, "quality": q}
            headers = {"X-Emby-Token": token}

            last_err = None
            for base in bases:
                try:
                    r = _try_get(base + path, headers=headers, params=params)
                    ct = r.headers.get("Content-Type") or "image/jpeg"
                    return Response(
                        r.content,
                        mimetype=ct,
                        headers={"Cache-Control": "public, max-age=300"},
                    )
                except Exception as e:
                    last_err = e
                    continue

            abort(502)

        abort(404)


    # =====================================================================
    # ⚠️ END MONITORING ROUTES
    # =====================================================================


    @app.route("/api/monitoring/activity")
    def api_monitoring_activity():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              strftime('%Y-%m-%d', started_at) AS day,
              COUNT(*) AS sessions
            FROM media_session_history
            WHERE {where}
            GROUP BY strftime('%Y-%m-%d', started_at)
            ORDER BY day ASC
            """,
            params,
        )
        return json_rows(rows)





    @app.route("/api/monitoring/media_types")
    def api_monitoring_media_types():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            WITH norm AS (
              SELECT
                CASE
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film') THEN 'movie'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'series'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                  ELSE 'other'
                END AS media_type
              FROM media_session_history
              WHERE {where}
            )
            SELECT media_type, COUNT(*) AS sessions
            FROM norm
            GROUP BY media_type
            ORDER BY sessions DESC
            """,
            params,
        )


        return json_rows(rows)


    @app.route("/api/monitoring/per_server")
    def api_monitoring_per_server():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "h.started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              COALESCE(NULLIF(s.name, ''), 'Server ' || h.server_id) AS server_name,
              COUNT(*) AS sessions
            FROM media_session_history h
            LEFT JOIN servers s ON s.id = h.server_id
            WHERE {where}
            GROUP BY h.server_id
            ORDER BY sessions DESC
            """,
            params,
        )
        return json_rows(rows)




    @app.route("/api/monitoring/weekday")
    def api_monitoring_weekday():
        db = get_db()
        rng = request.args.get("range", "1m")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-1 month")
            where = "started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              CAST(strftime('%w', started_at) AS INTEGER) AS weekday,
              COUNT(*) AS sessions
            FROM media_session_history
            WHERE {where}
            GROUP BY CAST(strftime('%w', started_at) AS INTEGER)
            ORDER BY weekday
            """,
            params,
        )
        return json_rows(rows)


    @app.route("/api/monitoring/user/<int:user_id>/daily")
    def api_monitoring_user_daily(user_id: int):
        db = get_db()
        rng = request.args.get("range", "30d")

        if rng == "all":
            where = "1=1"
            params = (user_id,)
        else:
            delta = {
                "7d": "-7 days",
                "30d": "-30 days",
                "90d": "-90 days",
                "12m": "-12 months",
            }.get(rng, "-30 days")
            where = "h.started_at >= datetime('now', ?)"
            params = (user_id, delta)

        rows = db.query(
            f"""
            SELECT
              strftime('%Y-%m-%d', h.started_at) AS day,
              COUNT(*) AS plays,
              SUM(h.watch_ms) AS watch_ms
            FROM media_session_history h
            WHERE h.media_user_id = ?
              AND {where}
            GROUP BY strftime('%Y-%m-%d', h.started_at)
            ORDER BY day ASC
            """,
            params,
        )
        return json_rows(rows)





