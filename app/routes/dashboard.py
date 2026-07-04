# Auto-split from app.py (keep URLs/endpoints intact)
from core.monitoring.artwork import enrich_live_session_artwork
from core.usage_risk import build_usage_risk_report
from core.dashboard_servers import dashboard_server_preview
from core.dashboard_usage_risk import build_usage_risk_trend
from core.aggregate_cache import cached_aggregate
from core.dashboard_now_playing import load_dashboard_now_playing
from collections import Counter
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, make_response

from logging_utils import read_last_logs
from external.dashboard_quote_easter_egg import build_dashboard_quote_card

from web.helpers import get_db, table_exists

DASHBOARD_ACCESS_SERVER_COLUMNS = """
                s.id,
                s.name,
                s.type,
                s.url,
                s.local_url,
                s.public_url,
                s.status,
                s.last_checked
"""

DASHBOARD_ACCESS_LIBRARY_COLUMNS = """
                    l.id,
                    l.server_id,
                    l.name,
                    l.type,
                    l.section_id,
                    l.item_count
"""

def _no_store_response(html):
	response = make_response(html)
	response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
	response.headers["Pragma"] = "no-cache"
	response.headers["Expires"] = "0"
	return response

def _get_dashboard_next_tasks(db):
    if not table_exists(db, "tasks"):
        return {
            "items": [],
            "active": 0,
            "error": 0,
        }

    row = db.query_one(
        """
        SELECT
          SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS active,
          SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error
        FROM tasks
        """
    )

    tasks = db.query(
        """
        SELECT
          name,
          status,
          next_run,
          last_run
        FROM tasks
        WHERE enabled = 1
        ORDER BY
          CASE WHEN next_run IS NULL THEN 1 ELSE 0 END,
          datetime(next_run) ASC,
          LOWER(name) ASC
        LIMIT 8
        """
    ) or []

    return {
        "items": [dict(t) for t in tasks],
        "active": int((row["active"] if row else 0) or 0),
        "error": int((row["error"] if row else 0) or 0),
    }

def _build_usage_risk_dashboard(usage_risk_report, history_rows=None):
    rows = usage_risk_report.get("rows") or []

    reasons_counter = Counter()
    for row in rows:
        for reason in row.get("reasons") or []:
            reasons_counter[str(reason)] += 1

    total_reasons = sum(reasons_counter.values()) or 0
    top_reasons = []

    for label, count in reasons_counter.most_common(3):
        percent = round((count / total_reasons) * 100, 1) if total_reasons else 0
        top_reasons.append({
            "label": label,
            "count": count,
            "percent": percent,
        })

    result = {
        "top_reasons": top_reasons,
    }
    result.update(
        build_usage_risk_trend(
            history_rows or [],
            usage_risk_report.get("summary", {}).get("suggested", 0),
        )
    )
    return result

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

        dashboard_tasks = _get_dashboard_next_tasks(db)

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
        # DASHBOARD EXTRA STATS
        # --------------------------
        if table_exists(db, "stream_enforcements"):
            row = db.query_one(
                """
                SELECT COUNT(*) AS cnt
                FROM stream_enforcements
                WHERE action = 'kill'
                  AND datetime(created_at) >= datetime('now', '-7 days')
                """
            )
            stats["kills_7d"] = int(row["cnt"] or 0) if row else 0
        else:
            stats["kills_7d"] = 0

        subscription_stats = []
        subscription_stats_more = False
        subscription_plan_count = 0
        subscription_user_total = 0
        subscription_donut = "#334155 0% 100%"

        if table_exists(db, "subscription_templates"):
            subscription_stats = db.query(
                """
                SELECT
                  st.id,
                  st.name,
                  COUNT(vu.id) AS user_count
                FROM subscription_templates st
                LEFT JOIN vodum_users vu ON vu.subscription_template_id = st.id
                WHERE COALESCE(st.is_enabled, 1) = 1
                GROUP BY st.id, st.name
                ORDER BY user_count DESC, LOWER(st.name) ASC
                """
            ) or []

            subscription_stats = [dict(row) for row in subscription_stats]
            subscription_stats_more = len(subscription_stats) > 8

            subscription_plan_count = len(subscription_stats)
            subscription_user_total = sum(int(s.get("user_count") or 0) for s in subscription_stats)

            subscription_colors = ["#8b5cf6", "#f97316", "#60a5fa", "#22c55e", "#f43f5e", "#eab308", "#14b8a6", "#a78bfa"]
            donut_parts = []
            donut_cursor = 0.0

            for idx, sub in enumerate(subscription_stats):
                count = int(sub.get("user_count") or 0)
                percent = round((count / subscription_user_total) * 100, 1) if subscription_user_total else 0.0

                sub["percent"] = percent
                sub["color"] = subscription_colors[idx % len(subscription_colors)]

                if count > 0 and subscription_user_total > 0:
                    start = donut_cursor
                    end = donut_cursor + percent
                    donut_parts.append(f"{sub['color']} {start:.2f}% {end:.2f}%")
                    donut_cursor = end

            subscription_donut = ", ".join(donut_parts) if donut_parts else "#334155 0% 100%"

        # --------------------------
        # USAGE RISK SUMMARY
        # --------------------------
        usage_risk_summary = {
            "high": 0,
            "medium": 0,
            "low": 0,
            "suggested": 0,
        }
        usage_risk_dashboard = {
            "top_reasons": [],
            **build_usage_risk_trend([], 0),
        }

        try:
            usage_risk_report = cached_aggregate(
                "dashboard:usage-risk:30d",
                60,
                lambda: build_usage_risk_report(
                    db,
                    {"period_days": 30},
                    persist_history=False,
                ),
            )
            usage_risk_summary = usage_risk_report.get("summary") or usage_risk_summary
            history_rows = []
            if table_exists(db, "usage_risk_recommendations"):
                history_rows = db.query(
                    """
                    SELECT vodum_user_id, first_detected_at, last_detected_at
                    FROM usage_risk_recommendations
                    WHERE datetime(first_detected_at) <= datetime('now')
                      AND datetime(last_detected_at) >= datetime('now', '-13 days', 'start of day')
                    """
                ) or []
            usage_risk_dashboard = _build_usage_risk_dashboard(
                usage_risk_report,
                history_rows,
            )
        except Exception:
            pass

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

        for srv in servers:
            srv["peak_streams_7d"] = 0

        if table_exists(db, "media_session_history"):
            peak_rows = cached_aggregate(
                "dashboard:server-peaks:7d",
                120,
                lambda: [dict(row) for row in (db.query(
                    """
                WITH events AS (
                    SELECT server_id, datetime(started_at) AS ts, 1 AS delta
                    FROM media_session_history
                    WHERE stopped_at >= datetime('now', '-7 days')

                    UNION ALL

                    SELECT server_id, datetime(stopped_at) AS ts, -1 AS delta
                    FROM media_session_history
                    WHERE stopped_at >= datetime('now', '-7 days')
                ),
                running AS (
                    SELECT
                        server_id,
                        SUM(delta) OVER (
                            PARTITION BY server_id
                            ORDER BY ts
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        ) AS active_count
                    FROM events
                )
                SELECT server_id, MAX(active_count) AS peak
                FROM running
                GROUP BY server_id
                    """
                ) or [])],
            )

            peaks_by_server = {
                int(row["server_id"]): int(row["peak"] or 0)
                for row in peak_rows
            }

            for srv in servers:
                srv["peak_streams_7d"] = peaks_by_server.get(int(srv["id"]), 0)

        dashboard_servers = dashboard_server_preview(servers)

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

        now_playing = load_dashboard_now_playing(db)
        sessions = now_playing["sessions"]
        total_live = now_playing["total_live"]
        total_transcode = now_playing["total_transcode"]
        now_playing_stale = now_playing["stale_fallback"]
        sessions = [enrich_live_session_artwork(s, db) for s in sessions]


        idle_card = None
        if total_live <= 0:
            idle_card = build_dashboard_quote_card()


        # --------------------------
        # PAGE RENDERING
        # --------------------------
        return _no_store_response(render_template(
            "dashboard/dashboard.html",
            stats=stats,
            subscription_stats=subscription_stats,
            subscription_stats_more=subscription_stats_more,
            subscription_plan_count=subscription_plan_count,
            subscription_user_total=subscription_user_total,
            subscription_donut=subscription_donut,
            usage_risk_summary=usage_risk_summary,
            usage_risk_dashboard=usage_risk_dashboard,
            users_stats=users_stats,
            servers=servers,
            dashboard_servers=dashboard_servers,
            dashboard_tasks=dashboard_tasks,
            latest_logs=latest_logs,
            sessions=sessions,
            total_live=total_live,
            total_transcode=total_transcode,
            now_playing_stale=now_playing_stale,
            idle_card=idle_card,
            active_page="dashboard",
        ))

    @app.route("/dashboard/_next_tasks")
    def dashboard_next_tasks_partial():
        db = get_db()
        dashboard_tasks = _get_dashboard_next_tasks(db)

        return _no_store_response(render_template(
            "dashboard/partials/_next_tasks.html",
            dashboard_tasks=dashboard_tasks,
        ))

    @app.route("/dashboard/_now_playing")
    def dashboard_now_playing_partial():
        db = get_db()

        now_playing = load_dashboard_now_playing(db)
        sessions = now_playing["sessions"]
        sessions = [enrich_live_session_artwork(s, db) for s in sessions]
        total_live = now_playing["total_live"]
        total_transcode = now_playing["total_transcode"]

        idle_card = None
        if total_live <= 0:
            idle_card = build_dashboard_quote_card()


        return _no_store_response(render_template(
            "dashboard/partials/_now_playing.html",
            sessions=sessions,
            total_live=total_live,
            total_transcode=total_transcode,
            now_playing_stale=now_playing["stale_fallback"],
            idle_card=idle_card,
        ))


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
            f"""
            SELECT DISTINCT
{DASHBOARD_ACCESS_SERVER_COLUMNS}
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
                f"""
                SELECT DISTINCT
{DASHBOARD_ACCESS_LIBRARY_COLUMNS}
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
    


            

