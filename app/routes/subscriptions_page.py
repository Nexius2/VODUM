# Auto-split from app.py (keep URLs/endpoints intact)
import json
import math

from flask import render_template, request, redirect, url_for, flash

from tasks_engine import auto_enable_stream_enforcer, sync_expiry_tasks_from_settings, force_task_run, enable_and_run_task_by_name, set_tasks_enabled_by_names
from web.helpers import get_db, add_log
from logging_utils import get_logger


logger = get_logger("subscriptions")

DEFAULT_SUBSCRIPTION_TEMPLATES = [
    (
        "base sub",
        "2 streams / Same IP",
        365,
        70,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}},{"rule_type":"max_streams_per_ip","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
    ),
    (
        "Family sub",
        "4 streams",
        365,
        200,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":4,"allow_local_ip":true}}]',
    ),
    (
        "Plus sub",
        "3 streams / 2 IP",
        365,
        120,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":3,"allow_local_ip":true}},{"rule_type":"max_ips_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
    ),
]


SUBSCRIPTION_SETTINGS_COLUMNS = """
    default_subscription_days,
    delete_after_expiry_days,
    expiry_mode,
    warn_then_disable_days,
    usage_risk_enabled,
    usage_risk_send_upgrade_suggestions,
    usage_risk_send_stream_blocked_message,
    usage_risk_min_kills_before_suggestion,
    usage_risk_analysis_window_days,
    usage_risk_suggestion_cooldown_days,
    usage_risk_medium_threshold,
    usage_risk_high_threshold,
    subscription_plans_enabled_only,
    enable_cron_jobs
"""

STREAM_POLICY_PAGE_COLUMNS = """
                  p.id,
                  p.rule_type,
                  p.scope_type,
                  p.scope_id,
                  p.provider,
                  p.server_id,
                  p.priority,
                  p.is_enabled,
                  p.rule_value_json
"""

STREAM_POLICY_EDITOR_COLUMNS = """
            id,
            rule_type,
            scope_type,
            scope_id,
            provider,
            server_id,
            priority,
            is_enabled,
            rule_value_json
"""

SUBSCRIPTION_TEMPLATE_DUPLICATE_COLUMNS = """
            id,
            name,
            notes,
            duration_days,
            subscription_value,
            is_enabled,
            is_lifetime,
            policies_json
"""


def _restore_default_subscription_templates(db) -> int:
    restored = 0

    for name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json in DEFAULT_SUBSCRIPTION_TEMPLATES:
        existing = db.query_one(
            "SELECT id FROM subscription_templates WHERE name = ?",
            (name,),
        )

        if existing:
            continue

        db.execute(
            """
            INSERT INTO subscription_templates(
              name,
              notes,
              duration_days,
              subscription_value,
              is_default,
              is_enabled,
              policies_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                notes,
                duration_days,
                subscription_value,
                is_default,
                is_enabled,
                policies_json,
            ),
        )
        restored += 1

    return restored

def register(app):
    @app.route("/subscriptions", methods=["GET"])
    def subscriptions():
        db = get_db()
        tab = (request.args.get("tab") or "templates").strip().lower()
        if tab not in ("templates", "applications", "policies", "gifts", "settings"):
            tab = "templates"

        settings = db.query_one(f"SELECT {SUBSCRIPTION_SETTINGS_COLUMNS} FROM settings WHERE id = 1") if tab in ("templates", "settings") else None
        settings = dict(settings) if settings else {}

        servers = db.query("SELECT id, name, type FROM servers ORDER BY name") or [] if tab in ("templates", "applications", "policies", "gifts") else []

        gift_users = db.query("""
            SELECT
              vu.id,
              vu.username,
              vu.firstname,
              vu.lastname,
              vu.email,
              vu.second_email,
              vu.discord_name,
              vu.status,
              (
                SELECT GROUP_CONCAT(
                  COALESCE(mu.username, '') || ' ' || COALESCE(mu.email, ''),
                  ' '
                )
                FROM media_users mu
                WHERE mu.vodum_user_id = vu.id
              ) AS media_search
            FROM vodum_users vu
            WHERE vu.status IN ('active', 'pre_expired', 'reminder')
              AND EXISTS (
                SELECT 1
                FROM media_users mu
                WHERE mu.vodum_user_id = vu.id
              )
            ORDER BY LOWER(COALESCE(vu.username, '')) ASC, vu.id ASC
        """) or [] if tab == "gifts" else []

        gift_users = [dict(row) for row in gift_users]

        templates = db.query("""
            SELECT
              id,
              name,
              notes,
              duration_days,
              subscription_value,
              is_default,
              is_enabled,
              is_lifetime,
              policies_json,
              created_at,
              updated_at
            FROM subscription_templates
            ORDER BY is_default DESC, name
        """) or [] if tab in ("templates", "applications") else []
        templates = [dict(t) for t in templates]
        for t in templates:
            try:
                t['policies_count'] = len(json.loads(t.get('policies_json') or '[]'))
            except Exception:
                t['policies_count'] = 0

        enabled_templates = [t for t in templates if int(t.get("is_enabled") or 0) == 1]

        # Users list for applications tab (paginated)
        applications_page = max(request.args.get("applications_page", 1, type=int), 1)
        applications_per_page = request.args.get("applications_per_page", 20, type=int)
        if applications_per_page not in (20, 50, 100):
            applications_per_page = 20
        applications_offset = (applications_page - 1) * applications_per_page
        applications_search = " ".join(
            (request.args.get("applications_q") or "").split()
        ).strip()

        applications_where = []
        applications_params = []

        if applications_search:
            like = f"%{applications_search}%"
            applications_where.append("""
                (
                    COALESCE(vu.username, '') LIKE ?
                    OR COALESCE(vu.email, '') LIKE ?
                    OR COALESCE(vu.second_email, '') LIKE ?
                    OR COALESCE(vu.firstname, '') LIKE ?
                    OR COALESCE(vu.lastname, '') LIKE ?
                    OR COALESCE(vu.notes, '') LIKE ?
                    OR COALESCE(vu.discord_name, '') LIKE ?
                    OR COALESCE(vu.status, '') LIKE ?
                    OR COALESCE(st.name, '') LIKE ?
                    OR CAST(vu.id AS TEXT) LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM media_users mu_search
                        WHERE mu_search.vodum_user_id = vu.id
                          AND (
                            COALESCE(mu_search.username, '') LIKE ?
                            OR COALESCE(mu_search.email, '') LIKE ?
                          )
                    )
                )
            """)
            applications_params.extend([
                like,  # vu.username
                like,  # vu.email
                like,  # vu.second_email
                like,  # vu.firstname
                like,  # vu.lastname
                like,  # vu.notes
                like,  # vu.discord_name
                like,  # vu.status
                like,  # subscription template name
                like,  # vu.id
                like,  # media_users.username
                like,  # media_users.email
            ])

        users_query = """
            SELECT
              vu.id,
              vu.username,
              vu.email,
              vu.second_email,
              vu.firstname,
              vu.lastname,
              vu.notes,
              vu.discord_name,
              vu.status,
              vu.subscription_template_id,
              vu.max_streams_override,
              st.name AS subscription_template_name,
              (
                SELECT GROUP_CONCAT(
                  COALESCE(mu.username, '') || ' ' || COALESCE(mu.email, ''),
                  ' '
                )
                FROM media_users mu
                WHERE mu.vodum_user_id = vu.id
              ) AS media_search
            FROM vodum_users vu
            LEFT JOIN subscription_templates st ON st.id = vu.subscription_template_id
        """

        count_query = """
            SELECT COUNT(*) AS total
            FROM vodum_users vu
            LEFT JOIN subscription_templates st ON st.id = vu.subscription_template_id
        """

        if applications_where:
            where_sql = " WHERE " + " AND ".join(applications_where)
            users_query += where_sql
            count_query += where_sql

        users_query += """
            ORDER BY LOWER(COALESCE(vu.username, '')) ASC, vu.id ASC
            LIMIT ? OFFSET ?
        """

        applications_total_users = 0
        applications_total_pages = 1
        users = []
        if tab == "applications":
            total_row = db.query_one(count_query, tuple(applications_params)) or {"total": 0}
            applications_total_users = int(total_row["total"] or 0)
            applications_total_pages = max(math.ceil(applications_total_users / applications_per_page), 1)
            if applications_page > applications_total_pages:
                applications_page = applications_total_pages
                applications_offset = (applications_page - 1) * applications_per_page
            users = [dict(u) for u in (db.query(
                users_query,
                tuple(applications_params + [applications_per_page, applications_offset])
            ) or [])]

        policies = []
        edit_policy = None

        if tab == "policies":
            policies = db.query(f"""
                SELECT
{STREAM_POLICY_PAGE_COLUMNS},
                  s.name AS server_name,
                  vu.username AS scope_username,
                  vu.firstname AS scope_firstname,
                  vu.lastname AS scope_lastname,
                  vu.email AS scope_email,
                  vu.second_email AS scope_second_email,
                  vu.discord_name AS scope_discord_name,
                  (
                    SELECT GROUP_CONCAT(
                      COALESCE(mu.username, '') || ' ' || COALESCE(mu.email, ''),
                      ' '
                    )
                    FROM media_users mu
                    WHERE mu.vodum_user_id = vu.id
                  ) AS scope_media_search
                FROM stream_policies p
                LEFT JOIN servers s
                  ON s.id = p.server_id
                LEFT JOIN vodum_users vu
                  ON (p.scope_type = 'user' AND vu.id = p.scope_id)
                ORDER BY p.is_enabled DESC, p.priority ASC, p.id DESC
            """) or []

            policies = [dict(r) for r in policies]

            for p in policies:
                try:
                    p["_rule"] = json.loads(p.get("rule_value_json") or "{}")
                except Exception:
                    p["_rule"] = {}
                p["_is_system"] = bool(p["_rule"].get("system_tag"))
                p["_is_locked"] = bool(p["_rule"].get("locked"))
                p["_subscription_name"] = p["_rule"].get("subscription_name") or ""

            edit_policy_id = request.args.get("edit_policy_id", type=int)
            if edit_policy_id:
                ep = db.query_one(f"SELECT {STREAM_POLICY_EDITOR_COLUMNS} FROM stream_policies WHERE id = ?", (edit_policy_id,))
                if ep:
                    ep = dict(ep)
                    try:
                        ep["_rule"] = json.loads(ep.get("rule_value_json") or "{}")
                    except Exception:
                        ep["_rule"] = {}
                    edit_policy = ep

        return render_template(
            "subscriptions/subscriptions.html",
            tab=tab,
            settings=settings,
            servers=servers,
            gift_users=gift_users,
            templates=templates,
            enabled_templates=enabled_templates,
            users=users,
            applications_page=applications_page,
            applications_total_pages=applications_total_pages,
            applications_total_users=applications_total_users,
            applications_q=applications_search,
            applications_per_page=applications_per_page,
            policies=policies,
            edit_policy=edit_policy,
        )

    @app.post("/subscriptions/templates/enabled-only")
    def subscription_templates_enabled_only_save():
        db = get_db()
        enabled_only = 1 if request.form.get("enabled_only") == "1" else 0
        db.execute(
            "UPDATE settings SET subscription_plans_enabled_only = ? WHERE id = 1",
            (enabled_only,),
        )
        return redirect(url_for("subscriptions", tab="templates"))


    @app.route("/subscriptions/settings", methods=["POST"])
    def subscriptions_settings_save():
        db = get_db()

        settings = db.query_one(f"SELECT {SUBSCRIPTION_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        expiry_mode = (request.form.get("expiry_mode") or settings.get("expiry_mode") or "none").strip()
        if expiry_mode not in ("none", "warn_only", "warn_then_disable", "disable"):
            expiry_mode = "none"

        try:
            default_subscription_days = int(
                request.form.get("default_expiration_days", settings.get("default_subscription_days") or 90)
            )
        except Exception:
            default_subscription_days = int(settings.get("default_subscription_days") or 90)

        try:
            delete_after_expiry_days = int(
                request.form.get("delete_after_expiry_days", settings.get("delete_after_expiry_days") or 60)
            )
        except Exception:
            delete_after_expiry_days = int(settings.get("delete_after_expiry_days") or 60)

        try:
            warn_then_disable_days = int(
                request.form.get("warn_then_disable_days", settings.get("warn_then_disable_days") or 7)
            )
        except Exception:
            warn_then_disable_days = int(settings.get("warn_then_disable_days") or 7)

        usage_risk_enabled = 1 if request.form.get("usage_risk_enabled") == "1" else 0
        usage_risk_send_upgrade_suggestions = 1 if request.form.get("usage_risk_send_upgrade_suggestions") == "1" else 0
        usage_risk_send_stream_blocked_message = 1 if request.form.get("usage_risk_send_stream_blocked_message") == "1" else 0

        if expiry_mode in ("warn_only", "warn_then_disable"):
            usage_risk_send_stream_blocked_message = 1

        try:
            usage_risk_min_kills_before_suggestion = int(
                request.form.get(
                    "usage_risk_min_kills_before_suggestion",
                    settings.get("usage_risk_min_kills_before_suggestion") or 3,
                )
            )
        except Exception:
            usage_risk_min_kills_before_suggestion = int(settings.get("usage_risk_min_kills_before_suggestion") or 3)

        try:
            usage_risk_analysis_window_days = int(
                request.form.get(
                    "usage_risk_analysis_window_days",
                    settings.get("usage_risk_analysis_window_days") or 30,
                )
            )
        except Exception:
            usage_risk_analysis_window_days = int(settings.get("usage_risk_analysis_window_days") or 30)

        try:
            usage_risk_suggestion_cooldown_days = int(
                request.form.get(
                    "usage_risk_suggestion_cooldown_days",
                    settings.get("usage_risk_suggestion_cooldown_days") or 30,
                )
            )
        except Exception:
            usage_risk_suggestion_cooldown_days = int(settings.get("usage_risk_suggestion_cooldown_days") or 30)

        try:
            usage_risk_medium_threshold = int(
                request.form.get(
                    "usage_risk_medium_threshold",
                    settings.get("usage_risk_medium_threshold") or 40,
                )
            )
        except Exception:
            usage_risk_medium_threshold = int(settings.get("usage_risk_medium_threshold") or 40)

        try:
            usage_risk_high_threshold = int(
                request.form.get(
                    "usage_risk_high_threshold",
                    settings.get("usage_risk_high_threshold") or 75,
                )
            )
        except Exception:
            usage_risk_high_threshold = int(settings.get("usage_risk_high_threshold") or 75)

        if default_subscription_days < 1:
            default_subscription_days = 1

        if delete_after_expiry_days < 1:
            delete_after_expiry_days = 1

        if warn_then_disable_days < 1:
            warn_then_disable_days = 1

        if usage_risk_min_kills_before_suggestion < 1:
            usage_risk_min_kills_before_suggestion = 1

        if usage_risk_analysis_window_days < 7:
            usage_risk_analysis_window_days = 7

        if usage_risk_suggestion_cooldown_days < 1:
            usage_risk_suggestion_cooldown_days = 1

        if usage_risk_medium_threshold < 1:
            usage_risk_medium_threshold = 1

        if usage_risk_high_threshold <= usage_risk_medium_threshold:
            usage_risk_high_threshold = usage_risk_medium_threshold + 1

        if expiry_mode not in ("warn_then_disable", "warn_only"):
            warn_then_disable_days = int(settings.get("warn_then_disable_days") or 7)

        db.execute(
            """
            UPDATE settings
            SET default_subscription_days = ?,
                delete_after_expiry_days = ?,
                expiry_mode = ?,
                warn_then_disable_days = ?,
                disable_on_expiry = ?,
                usage_risk_enabled = ?,
                usage_risk_send_upgrade_suggestions = ?,
                usage_risk_send_stream_blocked_message = ?,
                usage_risk_min_kills_before_suggestion = ?,
                usage_risk_analysis_window_days = ?,
                usage_risk_suggestion_cooldown_days = ?,
                usage_risk_medium_threshold = ?,
                usage_risk_high_threshold = ?
            WHERE id = 1
            """,
            (
                default_subscription_days,
                delete_after_expiry_days,
                expiry_mode,
                warn_then_disable_days,
                1 if expiry_mode == "disable" else 0,
                usage_risk_enabled,
                usage_risk_send_upgrade_suggestions,
                usage_risk_send_stream_blocked_message,
                usage_risk_min_kills_before_suggestion,
                usage_risk_analysis_window_days,
                usage_risk_suggestion_cooldown_days,
                usage_risk_medium_threshold,
                usage_risk_high_threshold,
            ),
        )

        sync_expiry_tasks_from_settings(
            expiry_mode,
            int(settings.get("enable_cron_jobs") or 1),
        )

        if expiry_mode in ("warn_only", "warn_then_disable") or usage_risk_send_stream_blocked_message:
            db.execute(
                """
                UPDATE comm_templates
                SET enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = 'stream_blocked'
                """
            )

            force_task_run("expired_subscription_manager")

        if usage_risk_send_upgrade_suggestions:
            db.execute(
                """
                UPDATE comm_templates
                SET enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id
                    FROM comm_templates
                    WHERE key = 'usage_risk_upgrade_suggestion'
                       OR trigger_event = 'usage_risk_upgrade_suggestion'
                    ORDER BY
                        CASE WHEN key = 'usage_risk_upgrade_suggestion' THEN 0 ELSE 1 END,
                        id ASC
                    LIMIT 1
                )
                """
            )

            db.execute(
                """
                UPDATE comm_templates
                SET enabled = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE trigger_event = 'usage_risk_upgrade_suggestion'
                  AND id <> (
                    SELECT id
                    FROM comm_templates
                    WHERE key = 'usage_risk_upgrade_suggestion'
                       OR trigger_event = 'usage_risk_upgrade_suggestion'
                    ORDER BY
                        CASE WHEN key = 'usage_risk_upgrade_suggestion' THEN 0 ELSE 1 END,
                        id ASC
                    LIMIT 1
                  )
                """
            )

            enable_and_run_task_by_name("usage_risk_notifications")

        else:
            db.execute(
                """
                UPDATE comm_templates
                SET enabled = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE trigger_event = 'usage_risk_upgrade_suggestion'
                """
            )

            set_tasks_enabled_by_names(["usage_risk_notifications"], 0)

        add_log("info", "subscriptions", "Subscription settings updated")
        flash("settings_saved", "success")
        return redirect(url_for("subscriptions", tab="settings"))


    

    # -----------------------------
    # TEMPLATES (CRUD)
    # -----------------------------

    def _parse_json_list(raw: str):
        try:
            v = json.loads(raw or "[]")
            return v if isinstance(v, list) else []
        except Exception:
            return []

    def _policy_int_or_none(value):
        try:
            return int(value)
        except Exception:
            return None

    def _stream_user_policy_applies_to_policy(stream_policy, target_policy) -> bool:
        stream_provider = (stream_policy.get("provider") or "").strip() or None
        target_provider = (target_policy.get("provider") or "").strip() or None

        stream_server_id = _policy_int_or_none(stream_policy.get("server_id"))
        target_server_id = _policy_int_or_none(target_policy.get("server_id"))

        if stream_provider and not target_provider:
            return False

        if stream_provider and target_provider and stream_provider != target_provider:
            return False

        if stream_server_id is not None and target_server_id is None:
            return False

        if stream_server_id is not None and target_server_id is not None and stream_server_id != target_server_id:
            return False

        return True

    def _validate_subscription_template_policy_limits(policies: list) -> str | None:
        stream_user_policies = []

        for p in policies:
            if not isinstance(p, dict):
                continue

            if int(p.get("is_enabled") or 0) != 1:
                continue

            if (p.get("rule_type") or "").strip() != "max_streams_per_user":
                continue

            rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
            max_streams = _policy_int_or_none(rule.get("max"))

            if max_streams is not None and max_streams > 0:
                stream_user_policies.append(p)

        for p in policies:
            if not isinstance(p, dict):
                continue

            if int(p.get("is_enabled") or 0) != 1:
                continue

            if (p.get("rule_type") or "").strip() != "max_ips_per_user":
                continue

            rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
            max_ips = _policy_int_or_none(rule.get("max"))

            if max_ips is None or max_ips <= 0:
                continue

            applicable_stream_limits = []

            for stream_policy in stream_user_policies:
                if not _stream_user_policy_applies_to_policy(stream_policy, p):
                    continue

                stream_rule = stream_policy.get("rule") if isinstance(stream_policy.get("rule"), dict) else {}
                max_streams = _policy_int_or_none(stream_rule.get("max"))

                if max_streams is not None and max_streams > 0:
                    applicable_stream_limits.append(max_streams)

            if applicable_stream_limits and max_ips > min(applicable_stream_limits):
                return "subscription_template_invalid_ip_streams_limit"

        return None

    @app.post("/subscriptions/templates/save")
    def subscription_templates_save():
        db = get_db()
        template_id_raw = (request.form.get("template_id") or "").strip()
        template_id = int(template_id_raw) if template_id_raw.isdigit() else None

        name = (request.form.get("name") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        duration_days_raw = (request.form.get("duration_days") or "").strip()
        subscription_value_raw = (request.form.get("subscription_value") or "").strip()

        try:
            duration_days = int(duration_days_raw) if duration_days_raw else 30
        except Exception:
            duration_days = 30

        try:
            subscription_value = float(subscription_value_raw) if subscription_value_raw else 0
        except Exception:
            subscription_value = 0

        if subscription_value < 0:
            subscription_value = 0

        policies_json = (request.form.get("policies_json") or "[]").strip()
        policies = _parse_json_list(policies_json)
        is_default = 1 if request.form.get("is_default") == "1" else 0
        is_enabled = 1 if request.form.get("is_enabled") == "1" else 0
        is_lifetime = 1 if request.form.get("is_lifetime") == "1" else 0

        if is_lifetime:
            duration_days = 0
        elif duration_days < 1:
            duration_days = 1

        if not name:
            flash("subscription_template_name_required", "error")
            return redirect(url_for("subscriptions", tab="templates"))

        # Keep only allowed keys (defensive)
        clean = []
        any_enabled = False

        for p in policies:
            if not isinstance(p, dict):
                continue
            rule_type = (p.get("rule_type") or "").strip()
            if not rule_type:
                continue
            clean.append({
                "rule_type": rule_type,
                "provider": (p.get("provider") or "").strip() or None,
                "server_id": int(p["server_id"]) if str(p.get("server_id","")).isdigit() else None,
                "is_enabled": 1 if str(p.get("is_enabled","1")) == "1" else 0,
                "priority": int(p.get("priority") or 100),
                "rule": p.get("rule") if isinstance(p.get("rule"), dict) else {},
            })

        limit_error = _validate_subscription_template_policy_limits(clean)
        if limit_error:
            flash(limit_error, "error")
            return redirect(url_for("subscriptions", tab="templates"))

        if template_id:
            # Update
            existing = db.query_one("SELECT id, name FROM subscription_templates WHERE id = ?", (template_id,))
            if not existing:
                flash("subscription_template_not_found", "error")
                return redirect(url_for("subscriptions", tab="templates"))

            # Unique name check (allow same id)
            dup = db.query_one("SELECT id FROM subscription_templates WHERE name = ? AND id != ?", (name, template_id))
            if dup:
                flash("subscription_template_name_exists", "error")
                return redirect(url_for("subscriptions", tab="templates"))

            db.execute(
                """
                UPDATE subscription_templates
                SET
                  name=?,
                  notes=?,
                  duration_days=?,
                  subscription_value=?,
                  is_default=?,
                  is_enabled=?,
                  is_lifetime=?,
                  policies_json=?,
                  updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (name, notes, duration_days, subscription_value, is_default, is_enabled, is_lifetime, json.dumps(clean), template_id),
            )
            refreshed = 0
            assigned_users = db.query(
                "SELECT id FROM vodum_users WHERE subscription_template_id = ?",
                (template_id,),
            ) or []

            for row in assigned_users:
                try:
                    _apply_template_snapshot(db, int(row["id"]), template_id)
                    refreshed += 1
                except Exception as e:
                    add_log(
                        "error",
                        "subscriptions",
                        f"Failed to refresh subscription policies for user #{row['id']} after template update #{template_id}: {e}",
                    )

            add_log(
                "info",
                "subscriptions",
                f"Template updated: {name} (id={template_id}) - refreshed {refreshed} assigned user policy snapshot(s)"
            )
            flash("subscription_template_saved", "success")
        else:
            # Create
            dup = db.query_one("SELECT id FROM subscription_templates WHERE name = ?", (name,))
            if dup:
                flash("subscription_template_name_exists", "error")
                return redirect(url_for("subscriptions", tab="templates"))

            db.execute(
                """
                INSERT INTO subscription_templates(
                  name,
                  notes,
                  duration_days,
                  subscription_value,
                  is_default,
                  is_enabled,
                  is_lifetime,
                  policies_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, notes, duration_days, subscription_value, is_default, is_enabled, is_lifetime, json.dumps(clean)),
            )
            add_log("info", "subscriptions", f"Template created: {name}")
            flash("subscription_template_created", "success")

        if is_default:
            saved = db.query_one("SELECT id FROM subscription_templates WHERE name = ?", (name,))
            if saved:
                db.execute(
                    """
                    UPDATE subscription_templates
                    SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END
                    """,
                    (int(saved["id"]),),
                )

        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/<int:template_id>/duplicate")
    def subscription_templates_duplicate(template_id: int):
        db = get_db()
        tpl = db.query_one(f"SELECT {SUBSCRIPTION_TEMPLATE_DUPLICATE_COLUMNS} FROM subscription_templates WHERE id=?", (template_id,))
        if not tpl:
            flash("subscription_template_not_found", "error")
            return redirect(url_for("subscriptions", tab="templates"))

        tpl = dict(tpl)
        base_name = (tpl.get("name") or "Template").strip()
        new_name = f"{base_name} - Copy"
        # Ensure unique name
        i = 2
        while db.query_one("SELECT id FROM subscription_templates WHERE name = ?", (new_name,)):
            new_name = f"{base_name} - Copy {i}"
            i += 1

        db.execute(
            """
            INSERT INTO subscription_templates(
              name,
              notes,
              duration_days,
              subscription_value,
              is_default,
              is_enabled,
              is_lifetime,
              policies_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_name,
                tpl.get("notes") or "",
                tpl.get("duration_days") or 30,
                tpl.get("subscription_value") or 0,
                0,
                int(tpl.get("is_enabled") or 0),
                int(tpl.get("is_lifetime") or 0),
                tpl.get("policies_json") or "[]",
            ),
        )
        add_log("info", "subscriptions", f"Template duplicated: {base_name} -> {new_name}")
        flash("subscription_template_duplicated", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/restore-defaults")
    def subscription_templates_restore_defaults():
        db = get_db()

        restored = _restore_default_subscription_templates(db)

        add_log("info", "subscriptions", f"Default subscription templates restored: {restored}")
        flash("subscription_template_defaults_restored", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/<int:template_id>/toggle")
    def subscription_templates_toggle(template_id: int):
        db = get_db()

        tpl = db.query_one(
            "SELECT id, name, is_enabled, is_default FROM subscription_templates WHERE id = ?",
            (template_id,),
        )

        if not tpl:
            flash("subscription_template_not_found", "error")
            return redirect(url_for("subscriptions", tab="templates"))

        tpl = dict(tpl)
        new_enabled = 0 if int(tpl.get("is_enabled") or 0) == 1 else 1

        db.execute(
            """
            UPDATE subscription_templates
            SET is_enabled = ?,
                is_default = CASE WHEN ? = 0 THEN 0 ELSE is_default END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_enabled, new_enabled, template_id),
        )

        add_log(
            "info",
            "subscriptions",
            f"Template {'enabled' if new_enabled else 'disabled'}: {tpl.get('name')} (id={template_id})"
        )

        flash("subscription_template_saved", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/<int:template_id>/delete")
    def subscription_templates_delete(template_id: int):
        db = get_db()
        tpl = db.query_one("SELECT id, name FROM subscription_templates WHERE id=?", (template_id,))
        if not tpl:
            flash("subscription_template_not_found", "error")
            return redirect(url_for("subscriptions", tab="templates"))

        tpl = dict(tpl)
        name = tpl.get("name") or f"#{template_id}"

        # Unassign users (keep snapshot policies as-is)
        db.execute("UPDATE vodum_users SET subscription_template_id=NULL WHERE subscription_template_id=?", (template_id,))
        db.execute("DELETE FROM subscription_templates WHERE id=?", (template_id,))
        add_log("info", "subscriptions", f"Template deleted: {name} (id={template_id})")
        flash("subscription_template_deleted", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    # -----------------------------
    # APPLICATIONS (snapshot)
    # -----------------------------

    def _delete_locked_subscription_policies(db, vodum_user_id: int):
        rows = db.query(
            "SELECT id, rule_value_json FROM stream_policies WHERE scope_type='user' AND scope_id=?",
            (vodum_user_id,),
        ) or []
        for r in rows:
            try:
                rj = json.loads(r["rule_value_json"] or "{}")
            except Exception:
                rj = {}
            if rj.get("locked") and rj.get("subscription_name"):
                db.execute("DELETE FROM stream_policies WHERE id=?", (int(r["id"]),))

    def _clear_template_snapshot(db, vodum_user_id: int):
        _delete_locked_subscription_policies(db, vodum_user_id)
        db.execute(
            "UPDATE vodum_users SET subscription_template_id=NULL WHERE id=?",
            (vodum_user_id,),
        )

    def _apply_template_snapshot(db, vodum_user_id: int, template_id: int):
        tpl = db.query_one("SELECT id, name, policies_json FROM subscription_templates WHERE id=?", (template_id,))
        if not tpl:
            raise ValueError("subscription_template_not_found")

        tpl = dict(tpl)
        tname = tpl.get("name") or ""
        policies = _parse_json_list(tpl.get("policies_json") or "[]")

        # Replace existing subscription policies for that user
        _delete_locked_subscription_policies(db, vodum_user_id)

        any_enabled = False

        for p in policies:
            if not isinstance(p, dict):
                continue
            rule_type = (p.get("rule_type") or "").strip()
            if not rule_type:
                continue

            rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
            # Mark as subscription-locked
            rule = dict(rule)
            rule["locked"] = True
            rule["subscription_name"] = tname
            rule["subscription_template_id"] = template_id

            provider = (p.get("provider") or "").strip() or None
            server_id = int(p["server_id"]) if str(p.get("server_id","")).isdigit() else None
            is_enabled = 1 if str(p.get("is_enabled","1")) == "1" else 0
            if is_enabled == 1:
                any_enabled = True
            priority = int(p.get("priority") or 100)

            db.execute(
                """
                INSERT INTO stream_policies(scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, rule_value_json)
                VALUES ('user', ?, ?, ?, ?, ?, ?, ?)
                """,
                (vodum_user_id, provider, server_id, is_enabled, priority, rule_type, json.dumps(rule)),
            )

        db.execute("UPDATE vodum_users SET subscription_template_id=? WHERE id=?", (template_id, vodum_user_id))

        # Auto-enable stream_enforcer if at least one policy is enabled
        if any_enabled:
            auto_enable_stream_enforcer()

        return tname

    @app.post("/subscriptions/apply/user")
    def subscription_apply_user():
        db = get_db()
        user_id_raw = (request.form.get("user_id") or "").strip()
        template_id_raw = (request.form.get("template_id") or "").strip()
        confirm = (request.form.get("confirm_replace") or "0") == "1"

        clear_subscription = template_id_raw in ("", "none", "null")

        if not user_id_raw.isdigit() or (not clear_subscription and not template_id_raw.isdigit()):
            flash("subscription_apply_invalid", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        user_id = int(user_id_raw)
        template_id = int(template_id_raw) if not clear_subscription else None

        u = db.query_one("SELECT subscription_template_id FROM vodum_users WHERE id=?", (user_id,))
        existing_id = int(u["subscription_template_id"]) if (u and u["subscription_template_id"] is not None) else None

        if clear_subscription:
            if existing_id is not None and not confirm:
                flash("subscription_apply_replace_warning", "warning")
                return redirect(url_for("subscriptions", tab="applications"))

            _clear_template_snapshot(db, user_id)
            add_log("info", "subscriptions", f"Subscription removed for user #{user_id}")
            flash("subscription_apply_success", "success")
            return redirect(url_for("subscriptions", tab="applications"))

        if existing_id and existing_id != template_id and not confirm:
            flash("subscription_apply_replace_warning", "warning")
            return redirect(url_for("subscriptions", tab="applications"))

        try:
            tname = _apply_template_snapshot(db, user_id, template_id)
        except ValueError:
            flash("subscription_template_not_found", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        add_log("info", "subscriptions", f"Template applied to user #{user_id}: {tname} (template_id={template_id})")
        flash("subscription_apply_success", "success")
        return redirect(url_for("subscriptions", tab="applications"))

    @app.post("/subscriptions/apply/server")
    def subscription_apply_server_bulk():
        db = get_db()
        server_id_raw = (request.form.get("server_id") or "").strip()
        template_id_raw = (request.form.get("template_id") or "").strip()
        confirm = (request.form.get("confirm_replace") or "0") == "1"

        clear_subscription = template_id_raw in ("", "none", "null")

        if not server_id_raw.isdigit() or (not clear_subscription and not template_id_raw.isdigit()):
            flash("subscription_apply_invalid", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        server_id = int(server_id_raw)
        template_id = int(template_id_raw) if not clear_subscription else None

        rows = db.query(
            "SELECT DISTINCT vodum_user_id FROM media_users WHERE server_id=? AND vodum_user_id IS NOT NULL",
            (server_id,),
        ) or []
        user_ids = [int(r["vodum_user_id"]) for r in rows if r["vodum_user_id"] is not None]

        if not user_ids:
            flash("subscription_apply_no_users", "warning")
            return redirect(url_for("subscriptions", tab="applications"))

        if not confirm:
            any_has = db.query_one(
                "SELECT 1 FROM vodum_users WHERE id IN (%s) AND subscription_template_id IS NOT NULL LIMIT 1" %
                ",".join(["?"] * len(user_ids)),
                tuple(user_ids),
            )
            if any_has:
                flash("subscription_apply_replace_warning", "warning")
                return redirect(url_for("subscriptions", tab="applications"))

        applied = 0

        try:
            if clear_subscription:
                for uid in user_ids:
                    _clear_template_snapshot(db, uid)
                    applied += 1

                add_log(
                    "info",
                    "subscriptions",
                    f"Subscription removed in bulk for server #{server_id} ({applied} users)"
                )
                flash("subscription_apply_bulk_success", "success")
                return redirect(url_for("subscriptions", tab="applications"))

            tpl = db.query_one("SELECT name FROM subscription_templates WHERE id=?", (template_id,))
            tname = (tpl["name"] if tpl else "")

            for uid in user_ids:
                _apply_template_snapshot(db, uid, template_id)
                applied += 1

            add_log(
                "info",
                "subscriptions",
                f"Template bulk-applied to server #{server_id}: {tname} (template_id={template_id}) to {applied} users"
            )
            flash("subscription_apply_bulk_success", "success")
            return redirect(url_for("subscriptions", tab="applications"))

        except Exception:
            logger.exception(
                "Bulk subscription application failed | server_id=%s | template_id=%s | user_count=%s",
                server_id,
                template_id,
                len(user_ids),
            )
            flash("subscription_apply_failed", "error")
            return redirect(url_for("subscriptions", tab="applications"))


