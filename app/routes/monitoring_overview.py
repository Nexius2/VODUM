# Auto-split from app.py (keep URLs/endpoints intact)
import json
from typing import Optional

from flask import (
    render_template, request, url_for, make_response, jsonify,
)
from core.monitoring.artwork import (
    build_history_poster_url,
    build_history_backdrop_url,
    enrich_live_session_artwork,
)
from core.monitoring.snapshots import get_live_session_stats
from core.monitoring.overview_aggregates import build_monitoring_overview_aggregates
from core.usage_risk import build_usage_risk_report
from logging_utils import get_logger
from web.helpers import get_db

monitoring_logger = get_logger("monitoring_overview")

MONITORING_LIVE_SESSION_COLUMNS = """
                  ms.id,
                  ms.server_id,
                  ms.provider,
                  ms.session_key,
                  ms.media_user_id,
                  ms.external_user_id,
                  ms.media_key,
                  ms.media_type,
                  ms.title,
                  ms.grandparent_title,
                  ms.parent_title,
                  ms.state,
                  ms.progress_ms,
                  ms.duration_ms,
                  ms.is_transcode,
                  ms.bitrate,
                  ms.video_codec,
                  ms.audio_codec,
                  ms.client_name,
                  ms.client_product,
                  ms.device,
                  ms.ip,
                  ms.started_at,
                  ms.last_seen_at,
                  ms.raw_json,
                  ms.poster_ref_json,
                  ms.backdrop_ref_json,
                  ms.library_section_id,
                  ms.missing_count
""".strip()

STREAM_POLICY_COLUMNS = """
                  p.id,
                  p.scope_type,
                  p.scope_id,
                  p.provider,
                  p.server_id,
                  p.is_enabled,
                  p.priority,
                  p.rule_type,
                  p.rule_value_json,
                  p.created_at,
                  p.updated_at
""".strip()

def _empty_server_resource_stats(note=None):
    return {
        "server_cpu_pct": None,
        "server_ram_pct": None,
        "server_resource_available": False,
        "server_resource_note": note,
    }


def _load_server_resource_stats(db, server_ids, max_age_seconds=600):
    normalized_ids = []
    for sid in (server_ids or []):
        try:
            sid = int(sid or 0)
        except Exception:
            sid = 0
        if sid > 0:
            normalized_ids.append(sid)

    if not normalized_ids:
        return {}

    placeholders = ",".join(["?"] * len(normalized_ids))
    params = tuple(normalized_ids) + (f"-{int(max_age_seconds)} seconds",)

    rows = db.query(
        f"""
        SELECT
          server_id,
          cpu_pct,
          ram_pct,
          is_available,
          note,
          fetched_at
        FROM monitoring_server_resources
        WHERE server_id IN ({placeholders})
          AND datetime(fetched_at) >= datetime('now', ?)
        """,
        params,
    )

    out = {}
    for row in rows or []:
        row = dict(row)
        out[int(row["server_id"])] = {
            "server_cpu_pct": row.get("cpu_pct"),
            "server_ram_pct": row.get("ram_pct"),
            "server_resource_available": bool(row.get("is_available")),
            "server_resource_note": row.get("note"),
        }

    return out


def _apply_server_resource_stats(rows, resource_by_server, server_id_key="server_id"):
    for row in rows or []:
        try:
            server_id = int(row.get(server_id_key) or 0)
        except Exception:
            server_id = 0

        resource = resource_by_server.get(server_id) or _empty_server_resource_stats(note="unavailable")

        row["server_cpu_pct"] = resource.get("server_cpu_pct")
        row["server_ram_pct"] = resource.get("server_ram_pct")
        row["server_resource_available"] = bool(resource.get("server_resource_available"))
        row["server_resource_note"] = resource.get("server_resource_note")



def _build_history_poster_url(row, db=None):
    return build_history_poster_url(row, db)


def _build_history_backdrop_url(row, db=None):
    return build_history_backdrop_url(row, db)


def register(app):
    @app.route("/monitoring/policies/enforcements/by-user")
    def monitoring_policy_enforcements_by_user():
        db = get_db()

        actor_key = (request.args.get("actor_key") or "").strip()

        if actor_key.startswith("vodum:"):
            try:
                vodum_user_id = int(actor_key.split(":", 1)[1])
            except Exception:
                return jsonify({"ok": False, "error": "Invalid vodum actor key"}), 400

            where_clause = "e.vodum_user_id = ?"
            params = [vodum_user_id]

        elif actor_key.startswith("ext:"):
            external_user_id = actor_key.split(":", 1)[1].strip()
            if not external_user_id:
                return jsonify({"ok": False, "error": "Invalid external actor key"}), 400

            where_clause = "COALESCE(e.external_user_id, '') = ?"
            params = [external_user_id]

        else:
            return jsonify({"ok": False, "error": "Missing actor key"}), 400

        rows = db.query(f"""
            SELECT
              e.id AS enforcement_id,
              e.created_at,
              e.action,
              e.reason,
              e.provider,
              e.session_key,
              e.policy_id,
              e.server_id,
              e.vodum_user_id,
              e.external_user_id,
              e.account_username,
              e.ips_json,
              e.details_json,

              p.rule_type,
              p.scope_type,
              p.scope_id,
              p.priority AS policy_priority,
              p.is_enabled AS policy_enabled,
              p.rule_value_json,

              s.name AS server_name,
              vu.username AS vodum_username,

              CASE
                WHEN e.account_username IS NOT NULL AND TRIM(e.account_username) <> '' THEN e.account_username
                WHEN mu_acc.username IS NOT NULL AND TRIM(mu_acc.username) <> '' THEN mu_acc.username
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
            LEFT JOIN (
              SELECT server_id, external_user_id, MAX(username) AS username
              FROM media_users
              GROUP BY server_id, external_user_id
            ) mu_acc
              ON mu_acc.server_id = e.server_id
             AND mu_acc.external_user_id = e.external_user_id
            WHERE datetime(e.created_at) >= datetime('now', '-24 hours')
              AND {where_clause}
            ORDER BY e.created_at DESC
            LIMIT 200
        """, params) or []

        return jsonify({
            "ok": True,
            "rows": [dict(r) for r in rows],
        })
    @app.route("/monitoring")
    def monitoring_page():
        db = get_db()
        tab = request.args.get("tab", "overview")

        # Une session est considérée "live" si vue dans les 120 dernières secondes
        live_window_seconds = 300
        live_window_sql = f"-{live_window_seconds} seconds"

        # --------------------------
        # Serveurs (statuts) (utilisé partout)
        # --------------------------
        servers = db.query(
            """
            SELECT id, name, LOWER(TRIM(type)) AS type, url, local_url, public_url, token, status, last_checked
            FROM servers
            WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')
            ORDER BY LOWER(TRIM(type)), name
            """
        )
        servers = [dict(r) for r in (servers or [])]

        configured_server_count = len(servers or [])

        server_resource_stats = {}
        if tab in ("overview", "now_playing", "servers"):
            server_resource_stats = _load_server_resource_stats(
                db,
                [srv.get("id") for srv in servers],
                max_age_seconds=600,
            )

        server_stats = db.query_one(
            """
            SELECT
              SUM(CASE WHEN LOWER(TRIM(COALESCE(status, 'unknown'))) = 'up' THEN 1 ELSE 0 END) AS online,
              SUM(CASE WHEN LOWER(TRIM(COALESCE(status, 'unknown'))) = 'down' THEN 1 ELSE 0 END) AS offline,
              COUNT(*) AS total
            FROM servers
            WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')
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
            sessions_stats = get_live_session_stats(
                db,
                live_window_seconds=live_window_seconds,
                fallback_max_age_seconds=600,
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
                WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
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

            sessions = db.query(
                f"""
                SELECT
                  {MONITORING_LIVE_SESSION_COLUMNS},
                  s.name AS server_name,
                  s.type AS provider,
                  mu.username AS username
                FROM media_sessions ms
                JOIN servers s ON s.id = ms.server_id
                LEFT JOIN media_users mu ON mu.id = ms.media_user_id
                WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
                ORDER BY datetime(ms.last_seen_at) DESC
                """,
                (live_window_sql,),
            )

            sessions = [dict(r) for r in sessions]

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

                enriched = enrich_live_session_artwork(s, db)
                s.update(enriched)

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
                  e.media_type,
                  e.title,
                  mu.username AS username,
                  COALESCE(
                    json_extract(e.payload_json, '$.grandparent_title'),
                    json_extract(e.payload_json, '$.grandparentTitle')
                  ) AS series_title,
                  COALESCE(
                    json_extract(e.payload_json, '$.season_number'),
                    json_extract(e.payload_json, '$.ParentIndexNumber')
                  ) AS season_number,
                  COALESCE(
                    json_extract(e.payload_json, '$.episode_number'),
                    json_extract(e.payload_json, '$.IndexNumber')
                  ) AS episode_number
                FROM media_events e
                JOIN servers s ON s.id = e.server_id
                LEFT JOIN media_users mu ON mu.id = e.media_user_id
                ORDER BY e.ts DESC
                LIMIT 30
                """
            )

        # --------------------------
        # Données overview uniquement
        # --------------------------
        if tab == "overview":
            overview_aggregates = build_monitoring_overview_aggregates(db, sessions_stats)
            stats_7d = overview_aggregates["stats_7d"]
            top_users_30d = overview_aggregates["top_users_30d"]
            top_content_30d = overview_aggregates["top_content_30d"]
            top_movies_30d = overview_aggregates["top_movies_30d"]
            concurrent_7d = overview_aggregates["concurrent_7d"]

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
        policy_scope_breakdown = {}
        policy_top_users_30d = []
        policy_recent_enforcements = []
        policy_enforcement_page = 1
        policy_enforcement_total_pages = 1
        policy_enforcement_total = 0
        policy_grouped_enforcements = []
        policy_tracked_state = {}

        usage_risk_report = {
            "enabled": True,
            "summary": {"high": 0, "medium": 0, "low": 0, "suggested": 0},
            "rows": [],
            "filters": {},
        }
        usage_risk_filters = {}
        subscription_templates = []
        stream_policy_types = []
        

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
                like = f"%{q}%"
                where.append("""
                    (
                        COALESCE(h.title, '') LIKE ?
                        OR COALESCE(h.grandparent_title, '') LIKE ?
                        OR COALESCE(h.media_type, '') LIKE ?
                        OR COALESCE(h.device, '') LIKE ?
                        OR COALESCE(h.client_name, '') LIKE ?
                        OR COALESCE(h.ip, '') LIKE ?
                        OR COALESCE(mu.username, '') LIKE ?
                        OR COALESCE(mu.email, '') LIKE ?
                        OR COALESCE(vu.username, '') LIKE ?
                        OR COALESCE(vu.email, '') LIKE ?
                        OR COALESCE(vu.second_email, '') LIKE ?
                        OR COALESCE(vu.firstname, '') LIKE ?
                        OR COALESCE(vu.lastname, '') LIKE ?
                        OR COALESCE(vu.discord_name, '') LIKE ?
                        OR COALESCE(s.name, '') LIKE ?
                    )
                """)
                params += [like] * 15
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
                LEFT JOIN media_users mu ON mu.id = h.media_user_id
                LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
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
                LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
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

        elif tab == "usage_risk":
            usage_risk_filters = {
                "q": (request.args.get("q") or "").strip(),
                "risk_level": (request.args.get("risk_level") or "").strip(),
                "subscription_id": request.args.get("subscription_id", type=int, default=0),
                "server_id": request.args.get("server_id", type=int, default=0),
                "policy": (request.args.get("policy") or "").strip(),
                "period_days": request.args.get("period_days", type=int, default=30),
            }

            usage_risk_report = build_usage_risk_report(db, usage_risk_filters)

            subscription_templates = db.query(
                """
                SELECT id, name
                FROM subscription_templates
                WHERE is_enabled = 1
                ORDER BY subscription_value ASC, name ASC
                """
            ) or []
            subscription_templates = [dict(r) for r in subscription_templates]

            stream_policy_types = db.query(
                """
                SELECT DISTINCT rule_type
                FROM stream_policies
                WHERE TRIM(COALESCE(rule_type, '')) <> ''
                ORDER BY rule_type ASC
                """
            ) or []
            stream_policy_types = [dict(r) for r in stream_policy_types]

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
                        mu.email AS mu_email,
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
                        COALESCE(vu.username, MIN(b.mu_username)) AS username,
                        GROUP_CONCAT(
                          COALESCE(b.mu_username, '') || ' ' || COALESCE(b.mu_email, ''),
                          ' '
                        ) AS media_search
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
                      OR COALESCE(vu.discord_name,'') LIKE ?
                      OR COALESCE(n.media_search,'') LIKE ?
                    )
                    """,
                    (like, like, like, like, like, like, like, like, like),
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
                  OR COALESCE(vu.discord_name,'') LIKE ?
                  OR COALESCE(n.media_search,'') LIKE ?
                )
                f"""

                params.extend([like, like, like, like, like, like, like, like, like])


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
                    mu.email AS mu_email,
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
                    COALESCE(vu.username, MIN(b.mu_username)) AS username,
                    GROUP_CONCAT(
                      COALESCE(b.mu_username, '') || ' ' || COALESCE(b.mu_email, ''),
                      ' '
                    ) AS media_search
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
            policy_enforcement_page = max(request.args.get("enforcement_page", 1, type=int), 1)
            policy_enforcement_per_page = 12
            policy_enforcement_count = db.query_one(
                "SELECT COUNT(*) AS total FROM stream_enforcements"
            ) or {"total": 0}
            policy_enforcement_total = int(policy_enforcement_count["total"] or 0)
            policy_enforcement_total_pages = max(
                (policy_enforcement_total + policy_enforcement_per_page - 1) // policy_enforcement_per_page,
                1,
            )
            policy_enforcement_page = min(policy_enforcement_page, policy_enforcement_total_pages)
            policy_enforcement_offset = (policy_enforcement_page - 1) * policy_enforcement_per_page

            policies = db.query(f"""
                SELECT
                  {STREAM_POLICY_COLUMNS},
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
                ep = db.query_one(f"SELECT {STREAM_POLICY_COLUMNS} FROM stream_policies p WHERE p.id = ?", (edit_policy_id,))
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
                      WHEN e.account_username IS NOT NULL AND TRIM(e.account_username) <> '' THEN e.account_username
                      WHEN mu_acc.username IS NOT NULL AND TRIM(mu_acc.username) <> '' THEN mu_acc.username
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
                  LEFT JOIN (
                    SELECT server_id, external_user_id, MAX(username) AS username
                    FROM media_users
                    GROUP BY server_id, external_user_id
                  ) mu_acc
                    ON mu_acc.server_id = e.server_id
                   AND mu_acc.external_user_id = e.external_user_id
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
                  e.id AS enforcement_id,
                  e.created_at,
                  e.action,
                  e.reason,
                  e.provider,
                  e.session_key,
                  e.policy_id,
                  e.server_id,
                  e.vodum_user_id,
                  e.external_user_id,
                  e.account_username,
                  e.ips_json,
                  e.details_json,

                  p.rule_type,
                  p.scope_type,
                  p.scope_id,
                  p.priority AS policy_priority,
                  p.is_enabled AS policy_enabled,
                  p.rule_value_json,

                  s.name AS server_name,
                  vu.username AS vodum_username,

                  CASE
                    WHEN e.account_username IS NOT NULL AND TRIM(e.account_username) <> '' THEN e.account_username
                    WHEN mu_acc.username IS NOT NULL AND TRIM(mu_acc.username) <> '' THEN mu_acc.username
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
                LEFT JOIN (
                  SELECT server_id, external_user_id, MAX(username) AS username
                  FROM media_users
                  GROUP BY server_id, external_user_id
                ) mu_acc
                  ON mu_acc.server_id = e.server_id
                 AND mu_acc.external_user_id = e.external_user_id
                ORDER BY e.created_at DESC
                LIMIT ? OFFSET ?
            """, (policy_enforcement_per_page, policy_enforcement_offset)) or []
            policy_recent_enforcements = [dict(r) for r in policy_recent_enforcements]
            policy_grouped_raw = db.query("""
                SELECT
                  e.id AS enforcement_id,
                  e.created_at,
                  e.action,
                  e.reason,
                  e.provider,
                  e.server_id,
                  e.vodum_user_id,
                  e.external_user_id,

                  p.rule_type,
                  s.name AS server_name,
                  vu.username AS vodum_username,

                  CASE
                    WHEN e.vodum_user_id IS NOT NULL THEN 'vodum:' || CAST(e.vodum_user_id AS TEXT)
                    ELSE 'ext:' || COALESCE(e.external_user_id, '')
                  END AS actor_key,

                  CASE
                    WHEN e.account_username IS NOT NULL AND TRIM(e.account_username) <> '' THEN e.account_username
                    WHEN mu_acc.username IS NOT NULL AND TRIM(mu_acc.username) <> '' THEN mu_acc.username
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
                LEFT JOIN (
                  SELECT server_id, external_user_id, MAX(username) AS username
                  FROM media_users
                  GROUP BY server_id, external_user_id
                ) mu_acc
                  ON mu_acc.server_id = e.server_id
                 AND mu_acc.external_user_id = e.external_user_id
                WHERE datetime(e.created_at) >= datetime('now', '-24 hours')
                ORDER BY e.created_at DESC
                LIMIT 1000
            """) or []

            grouped = {}

            for r in policy_grouped_raw:
                row = dict(r)
                actor_key = row.get("actor_key") or "unknown"

                if actor_key not in grouped:
                    grouped[actor_key] = {
                        "actor_key": actor_key,
                        "user_label": row.get("user_label") or "—",
                        "warn_count": 0,
                        "kill_count": 0,
                        "total_count": 0,
                        "last_action": row.get("action"),
                        "last_created_at": row.get("created_at"),
                        "last_server_name": row.get("server_name"),
                        "last_rule_type": row.get("rule_type"),
                        "last_reason": row.get("reason"),
                    }

                grouped[actor_key]["total_count"] += 1

                if row.get("action") == "warn":
                    grouped[actor_key]["warn_count"] += 1
                elif row.get("action") == "kill":
                    grouped[actor_key]["kill_count"] += 1

            policy_grouped_enforcements = sorted(
                grouped.values(),
                key=lambda x: (
                    int(x.get("kill_count") or 0),
                    int(x.get("warn_count") or 0),
                    int(x.get("total_count") or 0),
                    str(x.get("last_created_at") or ""),
                ),
                reverse=True
            )[:50]
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
                "users": "users_with_access",
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
                  (
                    SELECT COUNT(DISTINCT mul.media_user_id)
                    FROM media_user_libraries mul
                    JOIN media_users mu_acc ON mu_acc.id = mul.media_user_id
                    WHERE mul.library_id = l.id
                      AND LOWER(COALESCE(mu_acc.role, '')) != 'owner'
                  ) AS users_with_access,
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
                    COALESCE(
                      CAST(vu_ref.id AS TEXT),
                      'media:' || CAST(h.media_user_id AS TEXT),
                      'external:' || NULLIF(TRIM(h.external_user_id), ''),
                      'unknown'
                    ) AS viewer_key,
                    h.media_user_id,
                    h.media_key,
                    h.raw_json,
                    h.poster_ref_json,
                    h.backdrop_ref_json,
                    CASE
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey')), ''), '') <> ''
                        THEN 2
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) NOT IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND COALESCE(NULLIF(TRIM(h.media_key), ''), '') <> ''
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.ratingKey')), ''), '') = TRIM(h.media_key)
                        THEN 2
                      WHEN COALESCE(NULLIF(TRIM(h.poster_ref_json), ''), '') <> ''
                        THEN 1
                      ELSE 0
                    END AS artwork_rank,
                    h.stopped_at,
                    h.started_at,
                    CAST(h.library_section_id AS TEXT) AS history_library_section_id,
                    LOWER(TRIM(COALESCE(h.media_type, ''))) AS history_media_type,

                    CASE
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentTitle')), ''), '') <> ''
                        THEN TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentTitle'))
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) NOT IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND COALESCE(NULLIF(TRIM(h.media_key), ''), '') <> ''
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.ratingKey')), ''), '') = TRIM(h.media_key)
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.title')), ''), '') <> ''
                        THEN TRIM(json_extract(h.raw_json, '$.VideoOrTrack.title'))
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                        THEN TRIM(COALESCE(h.grandparent_title, 'Unknown'))
                      ELSE TRIM(COALESCE(h.title, 'Unknown'))
                    END AS display_title,

                    CASE
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND s.type = 'plex'
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey')), ''), '') <> ''
                        THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-id:' ||
                             TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey'))
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND s.type = 'jellyfin'
                           AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.NowPlayingItem.SeriesId')), ''), '') <> ''
                        THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-id:' ||
                             TRIM(json_extract(h.raw_json, '$.NowPlayingItem.SeriesId'))
                      WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                           AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                        THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-title:' || LOWER(TRIM(h.grandparent_title))
                      WHEN NULLIF(TRIM(h.media_key), '') IS NOT NULL
                        THEN 'server:' || CAST(h.server_id AS TEXT) || '|media:' || TRIM(h.media_key)
                      ELSE 'server:' || CAST(h.server_id AS TEXT) || '|title:' || LOWER(TRIM(COALESCE(h.title, 'Unknown')))
                    END AS media_group_key,

                    CASE
                      WHEN COALESCE(NULLIF(TRIM(h.session_key), ''), '') <> ''
                        THEN CAST(h.server_id AS TEXT) || '|session:' || TRIM(h.session_key) ||
                             '|started:' || COALESCE(h.started_at, '')
                      ELSE CAST(h.server_id AS TEXT) || '|viewer:' ||
                           COALESCE(CAST(h.media_user_id AS TEXT), NULLIF(TRIM(h.external_user_id), ''), 'unknown') ||
                           '|media:' || COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') ||
                           '|started:' || COALESCE(h.started_at, '') ||
                           '|client:' || LOWER(TRIM(COALESCE(h.client_name, '')))
                    END AS play_key

                  FROM media_session_history h
                  JOIN libraries l
                    ON l.server_id = h.server_id
                   AND CAST(l.section_id AS TEXT) = CAST(h.library_section_id AS TEXT)
                  JOIN servers s
                    ON s.id = l.server_id
                  LEFT JOIN media_users mu_ref
                    ON mu_ref.id = h.media_user_id
                  LEFT JOIN vodum_users vu_ref
                    ON vu_ref.id = mu_ref.vodum_user_id
                  WHERE {where_hist_sql}
                    AND COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
                ),
                plays_ranked AS (
                  SELECT
                    h.hist_id,
                    h.library_id,
                    h.library_name,
                    h.media_type,
                    h.server_id,
                    h.server_name,
                    h.provider,
                    h.vodum_user_id,
                    h.viewer_key,
                    h.media_key,
                    h.raw_json,
                    h.poster_ref_json,
                    h.backdrop_ref_json,
                    h.artwork_rank,
                    h.stopped_at,
                    h.display_title,
                    h.media_group_key,
                    h.play_key,
                    ROW_NUMBER() OVER (
                      PARTITION BY h.play_key
                      ORDER BY h.stopped_at DESC, h.hist_id DESC
                    ) AS rn
                  FROM hist h
                ),
                plays AS (
                  SELECT
                    hist_id,
                    library_id,
                    library_name,
                    media_type,
                    server_id,
                    server_name,
                    provider,
                    vodum_user_id,
                    viewer_key,
                    media_key,
                    raw_json,
                    poster_ref_json,
                    backdrop_ref_json,
                    artwork_rank,
                    stopped_at,
                    display_title,
                    media_group_key
                  FROM plays_ranked
                  WHERE rn = 1
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
                    COUNT(*) AS plays,
                    COUNT(DISTINCT viewer_key) AS user_count,
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
                    hist_id,
                    library_id,
                    media_group_key,
                    display_title,
                    media_key,
                    raw_json,
                    poster_ref_json,
                    backdrop_ref_json,
                    artwork_rank,
                    ROW_NUMBER() OVER (
                      PARTITION BY library_id, media_group_key
                      ORDER BY artwork_rank DESC, stopped_at DESC, hist_id DESC
                    ) AS rn
                  FROM plays
                ),
                ranked AS (
                  SELECT
                    m.library_id,
                    m.library_name,
                    m.media_type,
                    m.server_id,
                    m.server_name,
                    m.provider,
                    m.media_group_key,
                    COALESCE(ls.display_title, 'Unknown') AS display_title,
                    ls.hist_id AS hist_id,
                    ls.media_key AS media_key,
                    m.plays,
                    m.user_count,
                    m.last_play_at,
                    ls.raw_json,
                    ls.poster_ref_json,
                    ls.backdrop_ref_json,
                    ROW_NUMBER() OVER (
                      PARTITION BY m.library_id
                      ORDER BY m.plays DESC, m.user_count DESC, m.last_play_at DESC, COALESCE(ls.display_title, 'Unknown') ASC
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
                  hist_id,
                  media_key,
                  plays,
                  user_count,
                  last_play_at,
                  raw_json,
                  poster_ref_json,
                  backdrop_ref_json,
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
                item["poster_url"] = _build_history_poster_url(item, db)
                item["backdrop_url"] = _build_history_backdrop_url(item, db) or item["poster_url"]

                card["items"].append(item)
                card["total_plays"] += int(item.get("plays") or 0)

            library_top_cards = list(cards_by_library.values())

            for card in library_top_cards:
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
            # Range filter.
            # Les stats historiques utilisent media_session_history.
            # Les sessions live utilisent media_sessions et sont ajoutées aux mêmes agrégats.
            if server_range == "all":
                where_hist = "1=1"
                params_hist = ()
            else:
                delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(server_range, "-7 days")
                where_hist = "datetime(stopped_at) >= datetime('now', ?)"
                params_hist = (delta,)

            source_cte = f"""
                source AS (
                  SELECT
                    server_id,
                    media_user_id,
                    external_user_id,
                    session_key,
                    media_key,
                    media_type,
                    title,
                    grandparent_title,
                    parent_title,
                    started_at,
                    stopped_at,
                    MIN(
                      COALESCE(watch_ms, 0),
                      CASE
                        WHEN COALESCE(duration_ms, 0) > 0 THEN duration_ms
                        ELSE COALESCE(watch_ms, 0)
                      END
                    ) AS watch_ms,
                    was_transcode,
                    peak_bitrate,
                    ip,
                    client_product,
                    device,
                    library_section_id
                  FROM media_session_history
                  WHERE {where_hist}

                  UNION ALL

                  SELECT
                    server_id,
                    media_user_id,
                    external_user_id,
                    session_key,
                    media_key,
                    media_type,
                    title,
                    grandparent_title,
                    parent_title,
                    COALESCE(started_at, last_seen_at, CURRENT_TIMESTAMP) AS started_at,
                    CURRENT_TIMESTAMP AS stopped_at,
                    CASE
                      WHEN started_at IS NOT NULL AND COALESCE(duration_ms, 0) > 0 THEN
                        MIN(
                          COALESCE(duration_ms, 0),
                          MAX(0, CAST((julianday('now') - julianday(started_at)) * 86400000 AS INTEGER))
                        )
                      WHEN started_at IS NOT NULL THEN
                        MAX(0, CAST((julianday('now') - julianday(started_at)) * 86400000 AS INTEGER))
                      ELSE 0
                    END AS watch_ms,
                    is_transcode AS was_transcode,
                    bitrate AS peak_bitrate,
                    ip,
                    client_product,
                    device,
                    library_section_id
                  FROM media_sessions
                  WHERE datetime(last_seen_at) >= datetime('now', ?)
                ),
                plays AS (
                  SELECT
                    (CAST(server_id AS TEXT) || '|' ||
                     COALESCE(CAST(media_user_id AS TEXT), external_user_id, 'unknown_user') || '|' ||
                     COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                     strftime('%Y-%m-%d %H:%M', started_at)
                    ) AS play_key,

                    MAX(server_id) AS server_id,
                    MAX(media_user_id) AS media_user_id,
                    MAX(external_user_id) AS external_user_id,
                    MAX(session_key) AS session_key,
                    MAX(media_key) AS media_key,
                    MAX(media_type) AS media_type,
                    MAX(title) AS title,
                    MAX(grandparent_title) AS grandparent_title,
                    MAX(parent_title) AS parent_title,
                    MIN(started_at) AS started_at,
                    MAX(stopped_at) AS stopped_at,
                    MAX(COALESCE(watch_ms, 0)) AS watch_ms,
                    MAX(COALESCE(was_transcode, 0)) AS was_transcode,
                    MAX(COALESCE(peak_bitrate, 0)) AS peak_bitrate,
                    MAX(ip) AS ip,
                    MAX(client_product) AS client_product,
                    MAX(device) AS device,
                    MAX(library_section_id) AS library_section_id
                  FROM source
                  GROUP BY play_key
                )
            """

            params_source = tuple(params_hist) + (live_window_sql,)

            servers_combined = db.query_one(
                f"""
                WITH {source_cte}
                SELECT
                  COUNT(*) AS sessions,
                  COUNT(DISTINCT COALESCE(CAST(media_user_id AS TEXT), external_user_id)) AS active_users,
                  COALESCE(SUM(watch_ms), 0) AS watch_ms,
                  COALESCE(SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes,
                  AVG(NULLIF(peak_bitrate, 0)) AS avg_peak_bitrate,
                  MAX(peak_bitrate) AS max_peak_bitrate,
                  COUNT(DISTINCT NULLIF(TRIM(ip), '')) AS unique_ips
                FROM plays
                """,
                params_source,
            ) or {}
            servers_combined = dict(servers_combined)

            servers_details = db.query(
                f"""
                WITH {source_cte},
                live AS (
                  SELECT server_id, is_transcode
                  FROM media_sessions
                  WHERE datetime(last_seen_at) >= datetime('now', ?)
                )
                SELECT
                  s.id AS server_id,
                  s.name,
                  LOWER(TRIM(s.type)) AS type,
                  LOWER(TRIM(COALESCE(s.status, 'unknown'))) AS status,
                  s.last_checked,

                  (SELECT COUNT(*) FROM libraries l WHERE l.server_id = s.id) AS libraries,
                  (SELECT COUNT(*) FROM media_users mu WHERE mu.server_id = s.id) AS users,

                  (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id) AS live_sessions,
                  (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id AND x.is_transcode = 1) AS live_transcodes,
                  (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id AND COALESCE(x.is_transcode, 0) = 0) AS live_direct_plays,

                  (SELECT COUNT(*) FROM plays h WHERE h.server_id = s.id) AS sessions,
                  (SELECT COUNT(DISTINCT COALESCE(CAST(h.media_user_id AS TEXT), h.external_user_id)) FROM plays h WHERE h.server_id = s.id) AS active_users,
                  (SELECT COALESCE(SUM(h.watch_ms), 0) FROM plays h WHERE h.server_id = s.id) AS watch_ms,
                  (SELECT COALESCE(SUM(CASE WHEN h.was_transcode = 1 THEN 1 ELSE 0 END), 0) FROM plays h WHERE h.server_id = s.id) AS transcodes,
                  (SELECT AVG(NULLIF(h.peak_bitrate, 0)) FROM plays h WHERE h.server_id = s.id) AS avg_peak_bitrate,
                  (SELECT MAX(h.peak_bitrate) FROM plays h WHERE h.server_id = s.id) AS max_peak_bitrate,
                  (SELECT COUNT(DISTINCT NULLIF(TRIM(h.ip), '')) FROM plays h WHERE h.server_id = s.id) AS unique_ips

                FROM servers s
                WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
                ORDER BY LOWER(TRIM(s.type)), s.name
                """,
                params_source + (live_window_sql,),
            )
            servers_details = [dict(r) for r in servers_details]
            _apply_server_resource_stats(servers_details, server_resource_stats)

            servers_sessions_day = db.query(
                f"""
                WITH {source_cte}
                SELECT
                  date(stopped_at) AS day,
                  server_id,
                  COUNT(*) AS sessions
                FROM plays
                GROUP BY day, server_id
                ORDER BY day ASC
                """,
                params_source,
            )
            servers_sessions_day = [dict(r) for r in servers_sessions_day]

            servers_media_types = db.query(
                f"""
                WITH {source_cte},
                typed AS (
                  SELECT
                    server_id,
                    CASE
                      WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 'serie'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'serie'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 'movie'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                      WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                      ELSE 'other'
                    END AS media_type,
                    watch_ms
                  FROM plays
                )
                SELECT
                  server_id,
                  media_type,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(watch_ms), 0) AS watch_ms
                FROM typed
                GROUP BY server_id, media_type
                ORDER BY server_id, sessions DESC
                """,
                params_source,
            )
            servers_media_types = [dict(r) for r in servers_media_types]

            servers_clients = db.query(
                f"""
                WITH {source_cte}
                SELECT
                  p.server_id,
                  s.name AS server_name,
                  COALESCE(NULLIF(TRIM(p.client_product), ''), NULLIF(TRIM(p.device), ''), 'unknown') AS client,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(p.watch_ms), 0) AS watch_ms,
                  COALESCE(SUM(CASE WHEN p.was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
                FROM plays p
                JOIN servers s ON s.id = p.server_id
                GROUP BY p.server_id, s.name, client
                ORDER BY sessions DESC
                LIMIT 200
                """,
                params_source,
            )
            servers_clients = [dict(r) for r in servers_clients]

            servers_top_users = db.query(
                f"""
                WITH {source_cte}
                SELECT
                  p.server_id,
                  s.name AS server_name,
                  p.media_user_id,
                  COALESCE(mu.username, mu.email, p.external_user_id, 'Unknown user') AS user_label,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(p.watch_ms), 0) AS watch_ms,
                  COALESCE(SUM(CASE WHEN p.was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
                FROM plays p
                JOIN servers s ON s.id = p.server_id
                LEFT JOIN media_users mu ON mu.id = p.media_user_id
                GROUP BY p.server_id, s.name, p.media_user_id, p.external_user_id, user_label
                ORDER BY watch_ms DESC
                LIMIT 200
                """,
                params_source,
            )
            servers_top_users = [dict(r) for r in servers_top_users]

            servers_top_titles = db.query(
                f"""
                WITH {source_cte}
                SELECT
                  p.server_id,
                  s.name AS server_name,
                  TRIM(
                    COALESCE(NULLIF(TRIM(p.grandparent_title), '') || ' - ', '') ||
                    COALESCE(NULLIF(TRIM(p.parent_title), '') || ' - ', '') ||
                    COALESCE(NULLIF(TRIM(p.title), ''), 'Unknown')
                  ) AS full_title,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(p.watch_ms), 0) AS watch_ms,
                  COALESCE(SUM(CASE WHEN p.was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
                FROM plays p
                JOIN servers s ON s.id = p.server_id
                GROUP BY p.server_id, s.name, full_title
                ORDER BY watch_ms DESC
                LIMIT 200
                """,
                params_source,
            )
            servers_top_titles = [dict(r) for r in servers_top_titles]

            servers_unique_ips = db.query(
                f"""
                WITH {source_cte}
                SELECT
                  p.server_id,
                  s.name AS server_name,
                  COALESCE(NULLIF(TRIM(p.ip), ''), 'unknown') AS ip,
                  COUNT(*) AS sessions,
                  COALESCE(SUM(p.watch_ms), 0) AS watch_ms
                FROM plays p
                JOIN servers s ON s.id = p.server_id
                GROUP BY p.server_id, s.name, ip
                ORDER BY sessions DESC
                LIMIT 200
                """,
                params_source,
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
                "usage_risk": "monitoring/tabs/usage_risk.html",
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
                policy_enforcement_page=policy_enforcement_page,
                policy_enforcement_total_pages=policy_enforcement_total_pages,
                policy_enforcement_total=policy_enforcement_total,
                policy_grouped_enforcements=policy_grouped_enforcements,
                policy_tracked_state=policy_tracked_state,
                usage_risk_report=usage_risk_report,
                usage_risk_filters=usage_risk_filters,
                subscription_templates=subscription_templates,
                stream_policy_types=stream_policy_types,
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
            policy_enforcement_page=policy_enforcement_page,
            policy_enforcement_total_pages=policy_enforcement_total_pages,
            policy_enforcement_total=policy_enforcement_total,
            policy_grouped_enforcements=policy_grouped_enforcements,
            policy_tracked_state=policy_tracked_state,
            usage_risk_report=usage_risk_report,
            usage_risk_filters=usage_risk_filters,
            subscription_templates=subscription_templates,
            stream_policy_types=stream_policy_types,
        ))
        
        if sort_key and sort_dir:
            resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
            resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)
        return resp
