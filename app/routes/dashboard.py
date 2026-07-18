# Auto-split from app.py (keep URLs/endpoints intact)
from core.monitoring.artwork import enrich_live_session_artwork
from core.usage_risk import build_usage_risk_report
from core.dashboard_servers import dashboard_server_preview
from core.dashboard_usage_risk import build_usage_risk_trend
from core.aggregate_cache import cached_aggregate
from core.dashboard_now_playing import build_now_playing_fragment_key, load_dashboard_now_playing
from core.dashboard_widgets import (
    get_dashboard_next_tasks,
    get_dashboard_servers,
    get_dashboard_subscription_summary,
    get_dashboard_usage_risk,
)
from collections import Counter
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, make_response

from logging_utils import read_last_logs
from external.dashboard_quote_easter_egg import build_dashboard_quote_card

from web.helpers import get_db, table_exists

def _no_store_response(html):
	response = make_response(html)
	response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
	response.headers["Pragma"] = "no-cache"
	response.headers["Expires"] = "0"
	return response

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
            stype = (row["type"] or "").strip().lower()

            total = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE LOWER(TRIM(type)) = ?",
                (stype,),
            )["cnt"] or 0

            online = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE LOWER(TRIM(type)) = ? AND LOWER(TRIM(COALESCE(status, 'unknown'))) = 'up'",
                (stype,),
            )["cnt"] or 0

            offline = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE LOWER(TRIM(type)) = ? AND LOWER(TRIM(COALESCE(status, 'unknown'))) = 'down'",
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

        usage_risk_summary = {"high": 0, "medium": 0, "low": 0, "suggested": 0}
        usage_risk_dashboard = {"top_reasons": [], **build_usage_risk_trend([], 0)}

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
        ) or []

        servers = [dict(row) for row in servers]

        # --------------------------
        # LATEST LOGS (fichier)
        # --------------------------
        latest_logs = []

        lines = read_last_logs(30)  # on lit plus large, on filtre aprÃƒÂ¨s
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
        # PAGE RENDERING
        # --------------------------
        return _no_store_response(render_template(
            "dashboard/dashboard.html",
            stats=stats,
            usage_risk_summary=usage_risk_summary,
            usage_risk_dashboard=usage_risk_dashboard,
            users_stats=users_stats,
            servers=servers,
            latest_logs=latest_logs,
            active_page="dashboard",
        ))

    @app.route("/dashboard/_next_tasks")
    def dashboard_next_tasks_partial():
        db = get_db()
        dashboard_tasks = get_dashboard_next_tasks(db)

        return _no_store_response(render_template(
            "dashboard/partials/_next_tasks.html",
            dashboard_tasks=dashboard_tasks,
        ))

    @app.route("/dashboard/_subscription_summary")
    def dashboard_subscription_summary_partial():
        summary = get_dashboard_subscription_summary(get_db())
        return _no_store_response(render_template(
            "dashboard/partials/_streams_killed_subscriptions.html",
            **summary,
        ))

    @app.route("/dashboard/_usage_risk")
    def dashboard_usage_risk_partial():
        summary, dashboard = get_dashboard_usage_risk(get_db())
        return _no_store_response(render_template(
            "dashboard/partials/_usage_risk.html",
            usage_risk_summary=summary,
            usage_risk_dashboard=dashboard,
        ))

    @app.route("/dashboard/_servers")
    def dashboard_servers_partial():
        servers, preview = get_dashboard_servers(get_db())
        return _no_store_response(render_template(
            "dashboard/partials/_servers.html",
            servers=servers,
            dashboard_servers=preview,
        ))

    @app.route("/dashboard/_now_playing")
    def dashboard_now_playing_partial():
        db = get_db()

        now_playing = load_dashboard_now_playing(db)
        sessions = now_playing["sessions"]
        sessions = [enrich_live_session_artwork(s, db) for s in sessions]
        total_live = now_playing["total_live"]
        total_transcode = now_playing["total_transcode"]
        now_playing_key = build_now_playing_fragment_key(
            sessions,
            total_live=total_live,
            total_transcode=total_transcode,
            stale_fallback=now_playing["stale_fallback"],
        )

        idle_card = None
        if total_live <= 0:
            idle_card = build_dashboard_quote_card()

        return _no_store_response(render_template(
            "dashboard/partials/_now_playing.html",
            sessions=sessions,
            total_live=total_live,
            total_transcode=total_transcode,
            now_playing_stale=now_playing["stale_fallback"],
            now_playing_key=now_playing_key,
            idle_card=idle_card,
        ))
