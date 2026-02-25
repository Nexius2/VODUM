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
    @app.route("/monitoring/user/<int:user_id>")
    def monitoring_user_detail(user_id: int):
        db = get_db()

        view = (request.args.get("view") or "profile").strip().lower()
        if view not in ("profile", "history", "ip"):
            view = "profile"

        u = db.query_one(
            """
            SELECT
              mu.id,
              mu.username,
              mu.type,
              mu.server_id,
              mu.vodum_user_id,
              mu.external_user_id
            FROM media_users mu
            WHERE mu.id = ?
            """,
            (user_id,),
        )

        if not u:
            flash("invalid_user", "error")
            return redirect(url_for("monitoring_page", tab="users"))

        u = dict(u)

        # ✅ IMPORTANT :
        # Un même user existe 1 fois par serveur dans media_users.
        # On doit donc agréger tous les media_users.id qui ont le même vodum_user_id + external_user_id + type.
        if u.get("vodum_user_id"):
            linked_rows = db.query(
                """
                SELECT id, server_id
                FROM media_users
                WHERE vodum_user_id = ?
                ORDER BY type, server_id
                """,
                (u["vodum_user_id"],),
            )
            linked_ids = [r["id"] for r in linked_rows] or [user_id]
        else:
            linked_ids = [user_id]


        # ✅ Tous les media_users liés au même vodum_user (tous types: plex/jellyfin/...)
        all_identity_rows = db.query(
            """
            SELECT id, type, server_id, external_user_id
            FROM media_users
            WHERE vodum_user_id = ?
            ORDER BY type, server_id
            """,
            (u["vodum_user_id"],),
        )

        ids_by_type = {}
        for r in all_identity_rows:
            t = r["type"] or "unknown"
            ids_by_type.setdefault(t, []).append(r["id"])

        # Pour affichage dans le header
        u["ids_by_type"] = ids_by_type
        u["all_identity_rows"] = [dict(r) for r in all_identity_rows]

        # ✅ Camembert : serveurs réellement utilisés (plays) sur 30 jours
        # On groupe par server_id via join media_users (car media_session_history peut ne pas avoir server_id)
        placeholders = ",".join(["?"] * len(linked_ids))
        server_usage_rows = db.query(
            f"""
            SELECT
              mu.server_id AS server_id,
              COUNT(*) AS plays
            FROM media_session_history h
            JOIN media_users mu ON mu.id = h.media_user_id
            WHERE h.media_user_id IN ({placeholders})
              AND h.stopped_at >= datetime('now', '-30 days')
            GROUP BY mu.server_id
            ORDER BY plays DESC
            """,
            tuple(linked_ids),
        )

        server_ids = [r["server_id"] for r in server_usage_rows if r["server_id"] is not None]
        server_names = {}
        if server_ids:
            ph = ",".join(["?"] * len(server_ids))
            rows = db.query(
                f"SELECT id, name, type FROM servers WHERE id IN ({ph})",
                tuple(server_ids),
            )
            server_names = {
                x["id"]: f'{x["name"]}'
                for x in rows
            }


        server_usage = []
        for r in server_usage_rows:
            sid = r["server_id"]
            server_usage.append({
                "server_id": sid,
                "label": server_names.get(sid, f"server#{sid}" if sid is not None else "unknown"),
                "plays": int(r["plays"] or 0),
            })

        u["server_usage_30d"] = server_usage
        u["server_usage_30d_show"] = (len([x for x in server_usage if x.get("plays", 0) > 0]) > 1)

        # ✅ Donut : types de médias consommés (30 jours)
        media_types_rows = db.query(
            f"""
            WITH base AS (
              SELECT
                h.server_id,
                h.started_at,
                h.media_key,
                CASE
                  WHEN h.media_type IN ('episode', 'serie') THEN 'serie'
                  WHEN h.media_type = 'movie' THEN 'movie'
                  ELSE 'other'
                END AS kind,
                (CAST(h.server_id AS TEXT) || '|' ||
                 CAST(h.media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d', h.started_at)
                ) AS play_key
              FROM media_session_history h
              WHERE h.media_user_id IN ({placeholders})
                AND h.stopped_at >= datetime('now', '-30 days')
            ),
            plays AS (
              SELECT
                play_key,
                MAX(kind) AS kind
              FROM base
              GROUP BY play_key
            )
            SELECT
              kind,
              COUNT(*) AS plays
            FROM plays
            GROUP BY kind
            ORDER BY plays DESC
            """,
            tuple(linked_ids),
        )

        media_types = [{"label": r["kind"], "plays": int(r["plays"] or 0)} for r in media_types_rows]
        u["media_types_30d"] = media_types
        u["media_types_30d_show"] = (sum(x["plays"] for x in media_types) > 0)


        # ✅ Serveurs liés à CE user (pour affichage lisible dans le header)
        linked_server_ids = [r["server_id"] for r in linked_rows if r["server_id"] is not None]


        linked_servers = []
        if linked_server_ids:
            placeholders = ",".join(["?"] * len(linked_server_ids))
            linked_servers = db.query(
                f"""
                SELECT id, name, type
                FROM servers
                WHERE id IN ({placeholders})
                ORDER BY type, name
                """,
                tuple(linked_server_ids),
            )
            linked_servers = [dict(x) for x in linked_servers]

        # On met ça dans u pour le template
        u["linked_server_ids"] = linked_server_ids
        u["linked_servers"] = linked_servers


        # Helper pour générer "(?,?,?)" + params
        in_placeholders = ",".join(["?"] * len(linked_ids))
        in_sql = f"({in_placeholders})"


        # Global agg (all-time)
        agg = db.query_one(
            f"""
            WITH base AS (
              SELECT
                h.server_id,
                h.started_at,
                h.stopped_at,
                h.media_key,
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
                 strftime('%Y-%m-%d', h.started_at)
                ) AS play_key
              FROM media_session_history h
              WHERE h.media_user_id IN {in_sql}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at,
                MAX(watch_ms_capped) AS watch_ms
              FROM base
              GROUP BY play_key
            )
            SELECT
              COUNT(*) AS total_plays,
              COALESCE(SUM(watch_ms), 0) AS watch_ms,
              MAX(stopped_at) AS last_watch_at
            FROM plays
            """,
            tuple(linked_ids),
        ) or {"total_plays": 0, "watch_ms": 0, "last_watch_at": None}

        agg = dict(agg) if agg else {"total_plays": 0, "watch_ms": 0, "last_watch_at": None}

        u = dict(u)
        ms = agg.get("watch_ms") or 0
        u["total_plays"] = agg.get("total_plays") or 0
        u["last_watch_at"] = agg.get("last_watch_at")
        u["watch_time"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"

        # --------------------------
        # PROFILE (cards + top players)
        # --------------------------
        profile = {}
        if view == "profile":
            def _period_stats(delta_sql: str | None):
                if delta_sql is None:
                    row = db.query_one(
                        f"""
                        WITH base AS (
                          SELECT
                            h.server_id,
                            h.started_at,
                            h.stopped_at,
                            h.media_key,
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
                             strftime('%Y-%m-%d', h.started_at)
                            ) AS play_key
                          FROM media_session_history h
                          WHERE h.media_user_id IN {in_sql}
                        ),
                        plays AS (
                          SELECT
                            play_key,
                            MAX(stopped_at) AS stopped_at,
                            MAX(watch_ms_capped) AS watch_ms
                          FROM base
                          GROUP BY play_key
                        )
                        SELECT
                          COUNT(*) AS plays,
                          COALESCE(SUM(watch_ms), 0) AS watch_ms
                        FROM plays
                        """,
                        tuple(linked_ids),
                    )
                else:
                    row = db.query_one(
                        f"""
                        WITH base AS (
                          SELECT
                            h.server_id,
                            h.started_at,
                            h.stopped_at,
                            h.media_key,
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
                             strftime('%Y-%m-%d', h.started_at)
                            ) AS play_key
                          FROM media_session_history h
                          WHERE h.media_user_id IN {in_sql}
                            AND h.stopped_at >= datetime('now', ?)
                        ),
                        plays AS (
                          SELECT
                            play_key,
                            MAX(stopped_at) AS stopped_at,
                            MAX(watch_ms_capped) AS watch_ms
                          FROM base
                          GROUP BY play_key
                        )
                        SELECT
                          COUNT(*) AS plays,
                          COALESCE(SUM(watch_ms), 0) AS watch_ms
                        FROM plays
                        """,
                        tuple(linked_ids) + (delta_sql,),
                    )

                row = dict(row) if row else {"plays": 0, "watch_ms": 0}
                w = int(row.get("watch_ms") or 0)
                row["watch_time"] = f"{w // 3600000}h {((w % 3600000) // 60000)}m"
                row["plays"] = int(row.get("plays") or 0)
                return row


            profile["last_24h"] = _period_stats("-24 hours")
            profile["last_7d"]  = _period_stats("-7 days")
            profile["last_30d"] = _period_stats("-30 days")
            profile["all_time"] = _period_stats(None)

            # Top players (comme les tuiles Tautulli)
            top_players = db.query(
                f"""
                WITH base AS (
                  SELECT
                    COALESCE(NULLIF(h.client_name, ''), NULLIF(h.client_product,''), NULLIF(h.device,''), 'Unknown') AS player,
                    (CAST(h.server_id AS TEXT) || '|' ||
                     CAST(h.media_user_id AS TEXT) || '|' ||
                     COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d', h.started_at)
                    ) AS play_key
                  FROM media_session_history h
                  WHERE h.media_user_id IN {in_sql}
                ),
                plays AS (
                  SELECT
                    play_key,
                    MAX(player) AS player
                  FROM base
                  GROUP BY play_key
                )
                SELECT
                  player,
                  COUNT(*) AS plays
                FROM plays
                GROUP BY player
                ORDER BY plays DESC
                LIMIT 12
                """,
                tuple(linked_ids),
            )
            profile["top_players"] = [dict(r) for r in top_players]


        # --------------------------
        # HISTORY (ton existant, inchangé, mais déclenché seulement sur view=history)
        # --------------------------
        rows = []
        pagination = None
        q = (request.args.get("q") or "").strip()

        if view == "history":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            where = [f"h.media_user_id IN {in_sql}"]
            params = list(linked_ids)


            if q:
                where.append("(h.title LIKE ? OR h.grandparent_title LIKE ?)")
                params += [f"%{q}%", f"%{q}%"]

            where_sql = " AND ".join(where)

            total = db.query_one(
                f"""
                SELECT COUNT(*) AS cnt
                FROM media_session_history h
                WHERE {where_sql}
                """,
                tuple(params),
            ) or {"cnt": 0}

            rows = db.query(
                f"""
                SELECT
                  h.stopped_at,
                  s.name AS server_name,
                  s.type AS provider,
                  h.title,
                  h.grandparent_title,
                  h.media_type,
                  CASE WHEN h.was_transcode = 1 THEN 'transcode' ELSE 'directplay' END AS playback_type,
                  h.device,
                  h.client_name,
                  h.watch_ms,
                  h.ip
                FROM media_session_history h
                JOIN servers s ON s.id = h.server_id
                WHERE {where_sql}
                ORDER BY h.stopped_at DESC
                LIMIT {per_page} OFFSET ?
                """,
                tuple(params + [offset]),
            )

            rows = [dict(r) for r in rows]
            for r in rows:
                ms2 = r.get("watch_ms") or 0
                r["watch_time"] = f"{ms2 // 3600000}h {((ms2 % 3600000) // 60000)}m"
                if not r.get("ip"):
                    r["ip"] = "-"

            total_rows = int((total.get("cnt") if isinstance(total, dict) else total["cnt"]) or 0)
            total_pages = max(1, (total_rows + per_page - 1) // per_page)

            def build_url(p):
                args = dict(request.args)
                args["page"] = p
                args["view"] = "history"
                return url_for("monitoring_user_detail", user_id=user_id, **args)

            pagination = {
                "page": page,
                "total_pages": total_pages,
                "total_rows": total_rows,
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
            }

        # --------------------------
        # IP ADDRESSES (table type Tautulli)
        # --------------------------
        ip_rows = []
        if view == "ip":
            # Tri (déjà utilisé côté template)
            sort_key = (request.args.get("sort") or "last_seen").strip().lower()
            sort_dir = (request.args.get("dir") or "desc").strip().lower()
            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"

            sort_map = {
                "ip": "a.ip",
                "first_seen": "datetime(a.first_seen)",
                "last_seen": "datetime(a.last_seen)",
                "last_platform": "l.last_platform",
                "last_player": "l.last_player",
                "last_played": "l.last_title",
                "plays": "a.play_count",
                "watch": "l.last_watch_ms",  # ✅ watch = dernier media, pas total IP
            }
            order_expr = sort_map.get(sort_key, "datetime(a.last_seen)")
            order_sql = f"{order_expr} {sort_dir.upper()}"

            ip_rows = db.query(
                f"""
                WITH ranked AS (
                  SELECT
                    ip,
                    started_at,
                    stopped_at,
                    media_type,
                    title,
                    grandparent_title,
                    parent_title,
                    watch_ms,
                    duration_ms,
                    COALESCE(NULLIF(device,''), NULLIF(client_product,''), '-') AS platform,
                    COALESCE(NULLIF(client_name,''), NULLIF(client_product,''), '-') AS player,
                    ROW_NUMBER() OVER (PARTITION BY ip ORDER BY datetime(stopped_at) DESC) AS rn
                  FROM media_session_history
                  WHERE media_user_id IN {in_sql}
                    AND ip IS NOT NULL AND ip != ''
                ),
                last_per_ip AS (
                  SELECT
                    ip,
                    stopped_at AS last_seen,
                    platform AS last_platform,
                    player   AS last_player,
                    media_type AS last_media_type,
                    title AS last_title,
                    grandparent_title AS last_grandparent_title,
                    parent_title AS last_parent_title,
                    watch_ms AS last_watch_ms,
                    duration_ms AS last_duration_ms
                  FROM ranked
                  WHERE rn = 1
                ),
                agg AS (
                  SELECT
                    ip,
                    MIN(started_at) AS first_seen,
                    MAX(stopped_at) AS last_seen,
                    COUNT(*) AS play_count
                  FROM media_session_history
                  WHERE media_user_id IN {in_sql}
                    AND ip IS NOT NULL AND ip != ''
                  GROUP BY ip
                )
                SELECT
                  a.ip,
                  a.first_seen,
                  a.last_seen,
                  l.last_platform,
                  l.last_player,
                  l.last_media_type,
                  l.last_title,
                  l.last_grandparent_title,
                  l.last_parent_title,
                  l.last_watch_ms,
                  l.last_duration_ms,
                  a.play_count
                FROM agg a
                LEFT JOIN last_per_ip l ON l.ip = a.ip
                ORDER BY {order_sql}
                """,
                tuple(linked_ids) + tuple(linked_ids),
            )

            ip_rows = [dict(r) for r in ip_rows]

            def _fmt_last_played(r: dict) -> str:
                mt = (r.get("last_media_type") or "").strip().lower()
                title = (r.get("last_title") or "").strip()
                gp = (r.get("last_grandparent_title") or "").strip()
                parent = (r.get("last_parent_title") or "").strip()

                if not title and not gp:
                    return "-"

                # ⚠️ Chez toi Plex stocke les épisodes en "serie"
                if mt in ("episode", "serie"):
                    bits = [b for b in (gp, parent, title) if b]
                    return " • ".join(bits) if bits else "-"

                # film
                if mt == "movie":
                    return title or "-"

                bits = [b for b in (gp, title) if b]
                return " • ".join(bits) if bits else "-"

            def _fmt_ms(ms: int) -> str:
                ms = int(ms or 0)
                h = ms // 3600000
                m = (ms % 3600000) // 60000
                return f"{h}h {m}m"

            for r in ip_rows:
                r["last_played"] = _fmt_last_played(r)

                # ✅ watch time = celui du dernier média joué sur cette IP
                r["watch_time"] = _fmt_ms(r.get("last_watch_ms") or 0)

                # (optionnel) si tu veux aussi afficher la durée média
                # r["duration_time"] = _fmt_ms(r.get("last_duration_ms") or 0)



        return render_template(
            "monitoring/user_detail.html",
            active_page="monitoring",
            tab="users",
            user=u,
            view=view,
            profile=profile,
            rows=rows,
            ip_rows=ip_rows,
            q=q,
            pagination=pagination,
        )





    @app.route("/monitoring/session/<int:session_row_id>")
    def monitoring_session_detail(session_row_id: int):
        db = get_db()

        sess = db.query_one(
            """
            SELECT
              ms.*,
              s.name AS server_name,
              s.type AS provider,
              mu.username AS username
            FROM media_sessions ms
            JOIN servers s ON s.id = ms.server_id
            LEFT JOIN media_users mu ON mu.id = ms.media_user_id
            WHERE ms.id = ?
            """,
            (session_row_id,),
        )

        if not sess:
            flash("monitoring.session_not_found", "error")
            return redirect(url_for("monitoring_page"))

        events = db.query(
            """
            SELECT id, event_type, ts, payload_json
            FROM media_events
            WHERE server_id = ?
              AND session_key = ?
            ORDER BY ts DESC
            LIMIT 30
            """,
            (sess["server_id"], sess["session_key"]),
        )

        return render_template(
            "monitoring/session_detail.html",
            active_page="monitoring",
            sess=sess,
            events=events,
        )

    @app.post("/monitoring/policies/create")
    def stream_policy_create():
        db = get_db()

        policy_id_raw = (request.form.get("policy_id") or "").strip()
        policy_id = int(policy_id_raw) if policy_id_raw.isdigit() else None

        # Prevent edits on system-managed policies
        if policy_id:
            existing = db.query_one("SELECT rule_value_json FROM stream_policies WHERE id = ?", (policy_id,))
            if existing:
                try:
                    rj = json.loads(existing["rule_value_json"] or "{}")
                except Exception:
                    rj = {}
                if rj.get("system_tag"):
                    flash("System policy is read-only.", "error")
                    return redirect(url_for("monitoring_page", tab="policies"))

        rule_type = request.form.get("rule_type", "").strip()
        scope_type = request.form.get("scope_type", "global").strip()
        scope_id_raw = (request.form.get("scope_id") or "").strip()
        provider = (request.form.get("provider") or "").strip() or None
        server_id_raw = (request.form.get("server_id") or "").strip()
        priority = int((request.form.get("priority") or "100").strip() or 100)
        is_enabled = 1 if (request.form.get("is_enabled") or "1") == "1" else 0

        scope_id = int(scope_id_raw) if scope_id_raw.isdigit() else None
        server_id = int(server_id_raw) if server_id_raw.isdigit() else None

        selector = (request.form.get("selector") or "kill_newest").strip()
        warn_title = (request.form.get("warn_title") or "Stream limit").strip()
        warn_text = (request.form.get("warn_text") or "You reached your limit. If this continues, the most recent stream will be stopped.").strip()

        max_value = (request.form.get("max_value") or "").strip()
        max_kbps = (request.form.get("max_kbps") or "").strip()
        allowed_devices = (request.form.get("allowed_devices") or "").strip()
        allow_local_ip = 1 if (request.form.get("allow_local_ip") or "0") == "1" else 0

        rule = {
            "selector": selector,
            "warn_title": warn_title,
            "warn_text": warn_text,
        }

        # attach rule-specific fields
        if rule_type in ("max_streams_per_user", "max_transcodes_global", "max_streams_per_ip", "max_ips_per_user"):
            rule["max"] = int(max_value) if max_value.isdigit() else 1

        # options IP
        if rule_type in ("max_streams_per_ip", "max_ips_per_user"):
            rule["ignore_unknown"] = True
            rule["per_server"] = True

        # allow local IP bypass (LAN)
        if rule_type in ("max_streams_per_user", "max_streams_per_ip", "max_ips_per_user"):
            rule["allow_local_ip"] = bool(allow_local_ip)

        if rule_type == "max_bitrate_kbps":
            rule["max_kbps"] = int(max_kbps) if max_kbps.isdigit() else 20000

        if rule_type == "device_allowlist":
            allowed = []
            if allowed_devices:
                allowed = [x.strip() for x in allowed_devices.split(",") if x.strip()]
            rule["allowed"] = allowed

        if rule_type == "ban_4k_transcode":
            # rien de plus requis
            pass
        if policy_id:
            db.execute(
                """
                UPDATE stream_policies
                SET scope_type=?,
                    scope_id=?,
                    provider=?,
                    server_id=?,
                    is_enabled=?,
                    priority=?,
                    rule_type=?,
                    rule_value_json=?
                WHERE id=?
                """,
                (scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, json.dumps(rule), policy_id),
            )
            flash("Policy saved", "success")
        else:
            db.execute(
                """
                INSERT INTO stream_policies(scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, rule_value_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, json.dumps(rule)),
            )
            flash("Policy created", "success")

        # ✅ Auto-enable stream_enforcer si la policy est activée
        if is_enabled == 1:
            db.execute("""
                UPDATE tasks
                SET enabled = 1,
                    status = CASE WHEN status = 'disabled' THEN 'idle' ELSE status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE name = 'stream_enforcer'
            """)


        return redirect(url_for("monitoring_page", tab="policies"))


    @app.post("/monitoring/policies/<int:policy_id>/delete")
    def stream_policy_delete(policy_id: int):
        db = get_db()

        existing = db.query_one("SELECT rule_value_json FROM stream_policies WHERE id = ?", (policy_id,))
        if existing:
            try:
                rj = json.loads(existing["rule_value_json"] or "{}")
            except Exception:
                rj = {}
            if rj.get("system_tag"):
                flash("System policy cannot be deleted manually.", "error")
                return redirect(url_for("monitoring_page", tab="policies"))

        db.execute("DELETE FROM stream_policies WHERE id=?", (policy_id,))
        flash("Policy deleted", "success")
        return redirect(url_for("monitoring_page", tab="policies"))


    @app.get("/monitoring/policies/<int:policy_id>/edit")
    def stream_policy_edit(policy_id: int):
        return redirect(url_for("monitoring_page", tab="policies", edit_policy_id=policy_id))












