# Auto-split from app.py (keep URLs/endpoints intact)
from core.monitoring.artwork import enrich_live_session_artwork

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
            peak_rows = db.query(
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
            ) or []

            peaks_by_server = {
                int(row["server_id"]): int(row["peak"] or 0)
                for row in peak_rows
            }

            for srv in servers:
                srv["peak_streams_7d"] = peaks_by_server.get(int(srv["id"]), 0)

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

        live_window_seconds = 300
        live_window_sql = f"-{live_window_seconds} seconds"

        totals = db.query_one(
            """
            SELECT
              COUNT(*) AS total_live,
                SUM(
                    CASE
                      WHEN is_transcode = 1
                      THEN 1
                      ELSE 0
                    END
                ) AS total_transcode
            FROM media_sessions
            WHERE datetime(last_seen_at) >= datetime('now', ?)
            """,
            (live_window_sql,),
        )

        totals = dict(totals or {})

        total_live = int(totals.get("total_live") or 0)
        total_transcode = int(totals.get("total_transcode") or 0)

        sessions = db.query(
            """
            SELECT
              ms.*,
              s.name AS server_name,
              s.type AS provider,
              mu.username AS username
            FROM media_sessions ms
            JOIN servers s ON s.id = ms.server_id
            LEFT JOIN media_users mu ON mu.id = ms.media_user_id
            WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
            ORDER BY datetime(ms.last_seen_at) DESC
            LIMIT 6
            """,
            (live_window_sql,),
        )

        sessions = [dict(r) for r in sessions]
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
            users_stats=users_stats,
            servers=servers,
            latest_logs=latest_logs,
            sessions=sessions,
            total_live=total_live,
            total_transcode=total_transcode,
            idle_card=idle_card,
            active_page="dashboard",
        ))

    @app.route("/dashboard/_now_playing")
    def dashboard_now_playing_partial():
        db = get_db()

        live_window_seconds = 300
        live_window_sql = f"-{live_window_seconds} seconds"

        # Dashboard preview only: last 6 sessions
        totals = db.query_one(
            """
            SELECT
              COUNT(*) AS total_live,
              COALESCE(SUM(CASE WHEN ms.is_transcode = 1 THEN 1 ELSE 0 END), 0) AS total_transcode
            FROM media_sessions ms
            WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
            """,
            (live_window_sql,),
        )

        totals = dict(totals) if totals else {}

        total_live = int(totals.get("total_live") or 0)
        total_transcode = int(totals.get("total_transcode") or 0)

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
              ms.poster_ref_json,
              ms.backdrop_ref_json,
              ms.media_key
            FROM media_sessions ms
            JOIN servers s ON s.id = ms.server_id
            LEFT JOIN media_users mu ON mu.id = ms.media_user_id
            WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
            ORDER BY datetime(ms.last_seen_at) DESC
            LIMIT 6
            """,
            (live_window_sql,),
        )

        sessions = [dict(r) for r in sessions]
        sessions = [enrich_live_session_artwork(s, db) for s in sessions]

        idle_card = None
        if total_live <= 0:
            idle_card = build_dashboard_quote_card()


        return _no_store_response(render_template(
            "dashboard/partials/_now_playing.html",
            sessions=sessions,
            total_live=total_live,
            total_transcode=total_transcode,
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
    


            


