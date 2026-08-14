# Auto-split from app.py (keep URLs/endpoints intact)
import json

from flask import render_template, request, redirect, url_for, flash

from tasks_engine import auto_enable_stream_enforcer, sync_expiry_tasks_from_settings, force_task_run, enable_and_run_task_by_name, set_tasks_enabled_by_names
from web.helpers import get_db, add_log
from logging_utils import get_logger
from core.user_subscription_snapshots import (
    apply_template_snapshot,
    clear_template_snapshot,
)
from core.subscription_template_policies import (
    normalize_template_policies,
    parse_json_list,
    validate_subscription_template_policy_limits,
)
from core.default_subscription_templates import restore_default_subscription_templates
from core.subscription_page_data import (
    SUBSCRIPTION_SETTINGS_COLUMNS,
    load_subscription_application_users,
    load_subscription_page_catalog,
    load_subscription_policy_context,
)
from core.subscription_template_admin import (
    delete_subscription_template,
    duplicate_subscription_template,
    toggle_subscription_template,
)


logger = get_logger("subscriptions")

def register(app):
    @app.route("/subscriptions", methods=["GET"])
    def subscriptions():
        db = get_db()
        tab = (request.args.get("tab") or "templates").strip().lower()
        if tab not in ("templates", "applications", "policies", "gifts", "settings"):
            tab = "templates"

        catalog = load_subscription_page_catalog(db, tab=tab)
        settings = catalog["settings"]
        servers = catalog["servers"]
        gift_users = catalog["gift_users"]
        templates = catalog["templates"]
        enabled_templates = catalog["enabled_templates"]

        # Users list for applications tab (paginated)
        applications_page = max(request.args.get("applications_page", 1, type=int), 1)
        applications_per_page = request.args.get("applications_per_page", 20, type=int)
        applications_search = " ".join(
            (request.args.get("applications_q") or "").split()
        ).strip()
        applications_total_users = 0
        applications_total_pages = 1
        users = []
        if tab == "applications":
            application_context = load_subscription_application_users(
                db,
                page=applications_page,
                per_page=applications_per_page,
                search=applications_search,
            )
            users = application_context["users"]
            applications_page = application_context["page"]
            applications_per_page = application_context["per_page"]
            applications_search = application_context["search"]
            applications_total_users = application_context["total_users"]
            applications_total_pages = application_context["total_pages"]

        policies = []
        edit_policy = None

        if tab == "policies":
            edit_policy_id = request.args.get("edit_policy_id", type=int)
            policy_context = load_subscription_policy_context(
                db,
                edit_policy_id=edit_policy_id,
            )
            policies = policy_context["policies"]
            edit_policy = policy_context["edit_policy"]

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
        policies = parse_json_list(policies_json)
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
        clean = normalize_template_policies(policies)

        limit_error = validate_subscription_template_policy_limits(clean)
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
                    apply_template_snapshot(
                        db,
                        int(row["id"]),
                        template_id,
                        auto_enable_stream_enforcer,
                    )
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
        result = duplicate_subscription_template(db, template_id)
        if not result["ok"]:
            flash(result["reason"], "error")
            return redirect(url_for("subscriptions", tab="templates"))
        add_log(
            "info",
            "subscriptions",
            f"Template duplicated: {result['base_name']} -> {result['new_name']}",
        )
        flash("subscription_template_duplicated", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/restore-defaults")
    def subscription_templates_restore_defaults():
        db = get_db()

        restored = restore_default_subscription_templates(db)

        add_log("info", "subscriptions", f"Default subscription templates restored: {restored}")
        flash("subscription_template_defaults_restored", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/<int:template_id>/toggle")
    def subscription_templates_toggle(template_id: int):
        db = get_db()

        result = toggle_subscription_template(db, template_id)
        if not result["ok"]:
            flash(result["reason"], "error")
            return redirect(url_for("subscriptions", tab="templates"))

        add_log(
            "info",
            "subscriptions",
            f"Template {'enabled' if result['enabled'] else 'disabled'}: "
            f"{result['name']} (id={template_id})",
        )

        flash("subscription_template_saved", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/<int:template_id>/delete")
    def subscription_templates_delete(template_id: int):
        db = get_db()
        result = delete_subscription_template(db, template_id)
        if not result["ok"]:
            flash(result["reason"], "error")
            return redirect(url_for("subscriptions", tab="templates"))
        add_log(
            "info",
            "subscriptions",
            f"Template deleted: {result['name']} (id={template_id})",
        )
        flash("subscription_template_deleted", "success")
        return redirect(url_for("subscriptions", tab="templates"))

    # -----------------------------
    # APPLICATIONS (snapshot)
    # -----------------------------

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

            clear_template_snapshot(db, user_id)
            add_log("info", "subscriptions", f"Subscription removed for user #{user_id}")
            flash("subscription_apply_success", "success")
            return redirect(url_for("subscriptions", tab="applications"))

        if existing_id and existing_id != template_id and not confirm:
            flash("subscription_apply_replace_warning", "warning")
            return redirect(url_for("subscriptions", tab="applications"))

        try:
            tname = apply_template_snapshot(
                db,
                user_id,
                template_id,
                auto_enable_stream_enforcer,
            )
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
                    clear_template_snapshot(db, uid)
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
                apply_template_snapshot(
                    db,
                    uid,
                    template_id,
                    auto_enable_stream_enforcer,
                )
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


