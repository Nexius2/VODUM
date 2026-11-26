from core.error_reporting import log_handled_failure
# Auto-split from app.py (keep URLs/endpoints intact)
import json

from flask import render_template, request, redirect, url_for, flash

from tasks_engine import auto_enable_stream_enforcer
from web.helpers import get_db
from core.monitoring.precomputed_views import load_monitoring_user_stats
from core.monitoring.user_detail_stats import format_watch, sort_ip_rows

MONITORING_SESSION_DETAIL_COLUMNS = """
              ms.id,
              ms.server_id,
              ms.media_user_id,
              ms.session_key,
              ms.title,
              ms.state,
              ms.client_name,
              ms.device,
              ms.is_transcode,
              ms.last_seen_at,
              ms.raw_json
"""

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
        linked_rows = []

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
            linked_rows = [{"id": user_id, "server_id": u.get("server_id")}]
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

        # Serveurs liés à CE user (pour affichage lisible dans le header)
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
        u["linked_server_ids"] = linked_server_ids
        u["linked_servers"] = linked_servers

        # Helper pour générer "(?,?,?)" + params
        in_placeholders = ",".join(["?"] * len(linked_ids))
        in_sql = f"({in_placeholders})"

        # Aggregates are prepared by refresh_monitoring_statistics; this page
        # only reads them. Until the first result exists, the page says so.
        stats, statistics_snapshot = load_monitoring_user_stats(db, user_id)
        stats = stats or {}
        server_usage = stats.get("server_usage_30d") or []
        media_types = stats.get("media_types_30d") or []
        u["server_usage_30d"] = server_usage
        u["server_usage_30d_show"] = (len([x for x in server_usage if x.get("plays", 0) > 0]) > 1)
        u["media_types_30d"] = media_types
        u["media_types_30d_show"] = (sum(x["plays"] for x in media_types) > 0)
        ms = stats.get("watch_ms") or 0
        u["total_plays"] = stats.get("total_plays") or 0
        u["last_watch_at"] = stats.get("last_watch_at")
        u["watch_time"] = format_watch(ms)

        # --------------------------
        # PROFILE (cards + top players)
        # --------------------------
        profile = {}
        if view == "profile" and stats:
            profile = stats["profile"]


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
                like = f"%{q}%"
                where.append("""
                    (
                        COALESCE(h.title, '') LIKE ?
                        OR COALESCE(h.grandparent_title, '') LIKE ?
                        OR COALESCE(h.media_type, '') LIKE ?
                        OR COALESCE(h.device, '') LIKE ?
                        OR COALESCE(h.client_name, '') LIKE ?
                        OR COALESCE(h.ip, '') LIKE ?
                        OR COALESCE(s.name, '') LIKE ?
                    )
                """)
                params += [like] * 7

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
                "first_url": build_url(1),
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
                "last_url": build_url(total_pages),
            }

        # --------------------------
        # IP ADDRESSES (table type Tautulli)
        # --------------------------
        ip_rows = []
        if view == "ip":
            sort_key = (request.args.get("sort") or "last_seen").strip().lower()
            sort_dir = (request.args.get("dir") or "desc").strip().lower()
            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"
            ip_rows = sort_ip_rows(stats.get("ip_rows") or [], sort_key, sort_dir)

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
            statistics_snapshot=statistics_snapshot,
        )





    @app.route("/monitoring/session/<int:session_row_id>")
    def monitoring_session_detail(session_row_id: int):
        db = get_db()

        sess = db.query_one(
            f"""
            SELECT
{MONITORING_SESSION_DETAIL_COLUMNS},
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

    def _policy_redirect_response():
        redirect_endpoint = (request.form.get("redirect_endpoint") or request.args.get("redirect_endpoint") or "").strip()
        redirect_tab = (request.form.get("redirect_tab") or request.args.get("redirect_tab") or "policies").strip()

        if redirect_endpoint == "subscriptions":
            return redirect(url_for("subscriptions", tab=redirect_tab))

        return redirect(url_for("monitoring_page", tab="policies"))

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
                    log_handled_failure("policies.decode_existing_rule")
                    rj = {}
                if rj.get("system_tag") or rj.get("locked"):
                    flash("Policy is read-only.", "error")
                    return _policy_redirect_response()

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
        if rule_type in ("max_streams_per_ip", "max_ips_per_user"):
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

        # Auto-enable stream_enforcer si la policy est activée
        if is_enabled == 1:
            auto_enable_stream_enforcer()


        return _policy_redirect_response()


    @app.post("/monitoring/policies/<int:policy_id>/delete")
    def stream_policy_delete(policy_id: int):
        db = get_db()

        existing = db.query_one(
            "SELECT id, rule_value_json FROM stream_policies WHERE id = ?",
            (policy_id,),
        )

        if not existing:
            flash("Policy not found.", "error")
            return _policy_redirect_response()

        try:
            rule = json.loads(existing["rule_value_json"] or "{}")
        except Exception:
            log_handled_failure("policies.decode_deleted_rule")
            rule = {}

        if rule.get("system_tag") or rule.get("locked"):
            flash("Policy is read-only.", "error")
            return _policy_redirect_response()

        db.execute("DELETE FROM stream_policies WHERE id=?", (policy_id,))
        flash("Policy deleted", "success")
        return _policy_redirect_response()

    @app.post("/monitoring/policies/bulk-delete")
    def stream_policy_bulk_delete():
        db = get_db()

        policy_ids = request.form.getlist("policy_ids")
        cleaned_ids = []

        for value in policy_ids:
            try:
                cleaned_ids.append(int(value))
            except Exception:
                continue

        cleaned_ids = sorted(set(cleaned_ids))

        if not cleaned_ids:
            flash("No policy selected.", "error")
            return _policy_redirect_response()

        placeholders = ",".join(["?"] * len(cleaned_ids))

        rows = db.query(
            f"""
            SELECT id, rule_value_json
            FROM stream_policies
            WHERE id IN ({placeholders})
            """,
            tuple(cleaned_ids),
        ) or []

        deletable_ids = []
        skipped_count = 0

        for row in rows:
            try:
                rule = json.loads(row["rule_value_json"] or "{}")
            except Exception:
                log_handled_failure("policies.decode_bulk_deleted_rule")
                rule = {}

            if rule.get("system_tag") or rule.get("locked"):
                skipped_count += 1
                continue

            deletable_ids.append(int(row["id"]))

        if not deletable_ids:
            flash("No deletable policy selected.", "error")
            return _policy_redirect_response()

        delete_placeholders = ",".join(["?"] * len(deletable_ids))
        db.execute(
            f"DELETE FROM stream_policies WHERE id IN ({delete_placeholders})",
            tuple(deletable_ids),
        )

        deleted_count = len(deletable_ids)

        if skipped_count:
            flash(f"{deleted_count} deleted, {skipped_count} read-only skipped.", "success")
        else:
            flash(f"{deleted_count} polic{'y' if deleted_count == 1 else 'ies'} deleted.", "success")

        return _policy_redirect_response()

    @app.get("/monitoring/policies/<int:policy_id>/edit")
    def stream_policy_edit(policy_id: int):
        return redirect(url_for("monitoring_page", tab="policies", edit_policy_id=policy_id))












