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
    @app.route("/")
    def dashboard():
        db = get_db()

        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("servers_list"))


        # --------------------------
        # USER STATS (legacy: stats)
        # --------------------------
        stats = {}

        stats["total_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users"
        )["cnt"] or 0

        stats["active_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users WHERE status = 'active'"
        )["cnt"] or 0

        # expiring soon = reminder + pre_expired (legacy view)
        stats["expiring_soon"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users WHERE status IN ('pre_expired', 'reminder')"
        )["cnt"] or 0

        stats["expired_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users WHERE status = 'expired'"
        )["cnt"] or 0

        # --------------------------
        # USER STATS (new: users_stats used by dashboard.html)
        # --------------------------
        row = db.query_one(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
              SUM(CASE WHEN status = 'pre_expired' THEN 1 ELSE 0 END) AS pre_expired,
              SUM(CASE WHEN status = 'reminder' THEN 1 ELSE 0 END) AS reminder,
              SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired
            FROM vodum_users
            """
        )

        # db.query_one renvoie souvent sqlite3.Row -> pas de .get()
        row = dict(row) if row else {}

        users_stats = {
            "total": int(row.get("total") or 0),
            "active": int(row.get("active") or 0),
            "pre_expired": int(row.get("pre_expired") or 0),
            "reminder": int(row.get("reminder") or 0),
            "expired": int(row.get("expired") or 0),
        }

        # --------------------------
        # SERVER STATS (tous types)
        # --------------------------
        stats["server_types"] = {}

        server_types = db.query(
            """
            SELECT DISTINCT type
            FROM servers
            WHERE type IS NOT NULL AND type != ''
            ORDER BY type
            """
        )

        for row in server_types:
            stype = row["type"]

            total = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ?",
                (stype,),
            )["cnt"] or 0

            online = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ? AND status = 'up'",
                (stype,),
            )["cnt"] or 0

            offline = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ? AND status = 'down'",
                (stype,),
            )["cnt"] or 0

            stats["server_types"][stype] = {
                "total": int(total),
                "online": int(online),
                "offline": int(offline),
            }

        # --------------------------
        # TASK STATS
        # --------------------------
        if table_exists(db, "tasks"):
            stats["total_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks"
            )["cnt"] or 0

            stats["active_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE enabled = 1"
            )["cnt"] or 0

            stats["error_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE status = 'error'"
            )["cnt"] or 0
        else:
            stats["total_tasks"] = 0
            stats["active_tasks"] = 0
            stats["error_tasks"] = 0

        # --------------------------
        # SERVER LIST (tous types)
        # --------------------------
        servers = db.query(
            """
            SELECT
                s.id,
                s.name,
                s.type,
                COALESCE(s.url, s.local_url, s.public_url) AS url,
                s.status,
                s.last_checked
            FROM servers s
            ORDER BY s.type, s.name
            """
        )

        # --------------------------
        # LATEST LOGS (fichier)
        # --------------------------
        latest_logs = []

        lines = read_last_logs(30)  # on lit plus large, on filtre après
        ALLOWED_LEVELS = {"INFO", "ERROR", "CRITICAL"}

        for line in lines:
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue

            level = parts[1].strip().upper()
            if level not in ALLOWED_LEVELS:
                continue

            latest_logs.append({
                "created_at": parts[0].strip(),
                "level": level,
                "source": parts[2].strip(),
                "message": parts[3].strip(),
            })

        latest_logs = latest_logs[:10]

        # --------------------------
        # NOW PLAYING (Dashboard bubble) : same data as Monitoring / Now Playing
        # --------------------------
        live_window_seconds = 120
        live_window_sql = f"-{live_window_seconds} seconds"

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

        # --- Enrich Now Playing: SxxExx + poster (same as monitoring_overview.py)
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

                poster_item_id = now.get("SeriesId") or now.get("Id") or s.get("media_key")
                if poster_item_id:
                    s["poster_url"] = url_for(
                        "api_monitoring_poster",
                        server_id=s["server_id"],
                        item_id=str(poster_item_id),
                    )

        # --------------------------
        # PAGE RENDERING
        # --------------------------
        return render_template(
            "dashboard/dashboard.html",
            stats=stats,             
            users_stats=users_stats,  
            servers=servers,
            latest_logs=latest_logs,
            sessions=sessions,        
            active_page="dashboard",
        )

    @app.route("/dashboard/_now_playing")
    def dashboard_now_playing_partial():
        db = get_db()

        live_window_seconds = 120
        live_window_sql = f"-{live_window_seconds} seconds"

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

        return render_template(
            "dashboard/partials/_now_playing.html",
            sessions=sessions,
        )


    # -----------------------------
    # UTILISATEURS
    # -----------------------------

    def get_user_servers_with_access(vodum_user_id):
        """
        Retourne les serveurs associés à un utilisateur VODUM, avec
        la liste des bibliothèques auxquelles ses comptes media ont accès.
        """

        db = get_db()

        server_list = []

        # --------------------------------------------------
        # 1) Serveurs sur lesquels l'utilisateur possède un media_user
        # --------------------------------------------------
        servers = db.query(
            """
            SELECT DISTINCT s.*
            FROM servers s
            JOIN media_users mu ON mu.server_id = s.id
            WHERE mu.vodum_user_id = ?
            ORDER BY s.name
            """,
            (vodum_user_id,),
        )

        for s in servers:

            # --------------------------------------------------
            # 2) Bibliothèques accessibles via ses comptes media
            # --------------------------------------------------
            libraries = db.query(
                """
                SELECT DISTINCT l.*
                FROM libraries l
                JOIN media_user_libraries mul ON mul.library_id = l.id
                JOIN media_users mu ON mu.id = mul.media_user_id
                WHERE mu.vodum_user_id = ?
                  AND l.server_id = ?
                ORDER BY l.name
                """,
                (vodum_user_id, s["id"]),
            )

            server_list.append({
                "server": s,
                "libraries": libraries,
            })

        return server_list
    


            


