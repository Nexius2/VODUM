# Unified Communications UI (Email + Discord)

from flask import render_template, request, redirect, url_for, flash

from core.i18n import get_translator
from core.communication_i18n import communication_language_options, normalize_communication_language
from core.communications_recovery import retry_failed_scheduled_communications
from core.communications.default_templates import (
    is_stream_blocked_template,
    restore_default_comm_templates,
    subscription_expired_warning_requires_stream_blocked,
)
from core.communications.rules import (
    find_enabled_template_duplicate,
    normalize_campaign_targets,
)
from web.helpers import get_db, add_log, send_email_via_settings
from email_sender import send_email
from discord_utils import validate_discord_bot_token
from secret_store import decrypt_secret
from core.communication_template_admin import (
    sanitize_template_key as _sanitize_key,
    upsert_template_translation as _upsert_template_translation,
)
from core.communication_template_rules import normalize_template_rules
from core.communication_attachments import store_communication_attachments
from core.communication_configuration_form import parse_communication_configuration
from core.communication_page_data import (
    load_campaign_page_data, load_template_page_data,
    load_configuration_page_data,
)
from .communications_history import register_history_routes

from communications_engine import (
    fetch_campaign_attachments,
    queue_campaign_delivery,
)
from tasks_engine import enable_and_run_task_by_name
from logging_utils import get_logger


logger = get_logger("communications")


def _as_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default




def _selected_template_language(settings=None):
    raw = request.form.get("language") or request.args.get("language") or (settings or {}).get("communication_language") or "en"
    return normalize_communication_language(raw)



COMM_TRANSLATION_SETTINGS_COLUMNS = "default_language, communication_language"
COMM_TEST_CAMPAIGN_SETTINGS_COLUMNS = "contact_email"
COMM_CAMPAIGN_EDITOR_COLUMNS = """
    id,
    name,
    subject,
    body,
    server_id,
    trigger_provider,
    subscription_scope,
    subscription_template_id,
    status,
    is_test,
    created_at,
    updated_at,
    sent_at
"""

COMM_CAMPAIGN_LIST_COLUMNS = """
                c.id,
                c.name,
                c.subject,
                c.server_id,
                c.trigger_provider,
                c.subscription_scope,
                c.subscription_template_id,
                c.is_test,
                c.status,
                c.created_at,
                c.sent_at
"""
COMM_TEMPLATE_EDITOR_COLUMNS = """
    id,
    key,
    name,
    enabled,
    trigger_event,
    trigger_provider,
    expiration_change_direction,
    subscription_scope,
    subscription_template_id,
    days_before,
    days_after,
    subject,
    body,
    created_at,
    updated_at
"""

COMM_TEMPLATE_LIST_COLUMNS = """
              ct.id,
              ct.key,
              ct.name,
              ct.enabled,
              ct.trigger_event,
              ct.trigger_provider,
              ct.subscription_scope,
              ct.subscription_template_id,
              ct.days_before,
              ct.days_after,
              COALESCE(ctl.subject, ct.subject) AS subject
"""
COMM_CONFIG_SETTINGS_COLUMNS = """
    mailing_enabled,
    skip_never_used_accounts,
    mail_from,
    smtp_host,
    smtp_port,
    smtp_tls,
    smtp_user,
    smtp_pass,
    smtp_auth_method,
    smtp_oauth_access_token,
    discord_enabled,
    discord_bot_token,
    notifications_send_mode,
    notifications_order,
    user_notifications_can_override,
    communication_language
"""




def register(app):
    register_history_routes(app)

    @app.route("/communications")
    def communications_page():
        return redirect(url_for("communications_campaigns_page"))


    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    @app.route("/communications/campaigns/action", methods=["POST"])
    def communications_campaigns_action():
        db = get_db()
        t = get_translator()

        action_values = request.form.getlist("action")
        form_mode = (request.form.get("form_mode") or "").strip()
        action = (action_values[-1] if action_values else form_mode).strip().lower()

        if action == "create":
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            raw_server_id = (request.form.get("server_id") or "").strip()
            server_id = _as_int(raw_server_id, None) if raw_server_id else None
            is_test = 1 if request.form.get("is_test") == "1" else 0
            trigger_provider, subscription_scope, subscription_template_id = normalize_campaign_targets(db, request.form)

            if not name or not subject or not body:
                flash(t("comm_missing_fields"), "error")
                return redirect(url_for("communications_campaigns_page"))

            if server_id:
                exists = db.query_one("SELECT 1 FROM servers WHERE id = ?", (server_id,))
                if not exists:
                    server_id = None

            cur = db.execute(
                """
                INSERT INTO comm_campaigns(
                    name,
                    subject,
                    body,
                    server_id,
                    trigger_provider,
                    subscription_scope,
                    subscription_template_id,
                    status,
                    is_test,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, 'draft', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    name,
                    subject,
                    body,
                    server_id,
                    trigger_provider,
                    subscription_scope,
                    subscription_template_id,
                    is_test,
                ),
            )
            cid = getattr(cur, "lastrowid", None)

            store_communication_attachments(db, "campaign", int(cid), request.files.getlist("attachments"))

            add_log("info", "communications", "Campaign created", {"id": cid, "name": name})
            flash(t("comm_campaign_created"), "success")
            return redirect(url_for("communications_campaigns_page", load=cid))

        if action == "save":
            cid = request.form.get("campaign_id", type=int)
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            raw_server_id = (request.form.get("server_id") or "").strip()
            server_id = _as_int(raw_server_id, None) if raw_server_id else None
            is_test = 1 if request.form.get("is_test") == "1" else 0
            trigger_provider, subscription_scope, subscription_template_id = normalize_campaign_targets(db, request.form)

            if not cid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))

            if not name or not subject or not body:
                flash(t("comm_missing_fields"), "error")
                return redirect(url_for("communications_campaigns_page", load=cid))

            if server_id:
                exists = db.query_one("SELECT 1 FROM servers WHERE id = ?", (server_id,))
                if not exists:
                    server_id = None

            db.execute(
                """
                UPDATE comm_campaigns
                SET name = ?,
                    subject = ?,
                    body = ?,
                    server_id = ?,
                    trigger_provider = ?,
                    subscription_scope = ?,
                    subscription_template_id = ?,
                    is_test = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name,
                    subject,
                    body,
                    server_id,
                    trigger_provider,
                    subscription_scope,
                    subscription_template_id,
                    is_test,
                    cid,
                ),
            )

            store_communication_attachments(db, "campaign", int(cid), request.files.getlist("attachments"))

            add_log("info", "communications", "Campaign updated", {"id": cid})
            flash(t("comm_campaign_saved"), "success")
            return redirect(url_for("communications_campaigns_page", load=cid))

        if action == "delete":
            cid = request.form.get("campaign_id", type=int)

            if not cid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))

            existing = db.query_one("SELECT id FROM comm_campaigns WHERE id = ?", (cid,))
            if not existing:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))

            db.execute("DELETE FROM comm_campaigns WHERE id = ?", (cid,))

            add_log("info", "communications", "Campaign deleted", {"id": cid})
            flash(t("comm_campaign_deleted"), "success")
            return redirect(url_for("communications_campaigns_page"))

        if action == "send":
            cid = request.form.get("campaign_id", type=int)
            campaign = db.query_one(f"SELECT {COMM_CAMPAIGN_EDITOR_COLUMNS} FROM comm_campaigns WHERE id = ?", (cid,))
            if not campaign:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))
            campaign = dict(campaign)

            attachments = fetch_campaign_attachments(db, cid)

            if int(campaign.get("is_test") or 0) == 1:
                settings = db.query_one(f"SELECT {COMM_TEST_CAMPAIGN_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
                settings = dict(settings) if settings else {}

                admin_email = (settings.get("contact_email") or "").strip()
                if not admin_email:
                    db.execute("UPDATE comm_campaigns SET status='error', updated_at=CURRENT_TIMESTAMP WHERE id=?", (cid,))
                    flash(t("comm_admin_email_missing"), "error")
                    return redirect(url_for("communications_campaigns_page", load=cid))

                db.execute(
                    """
                    UPDATE comm_campaigns
                    SET status='pending',
                        sent_at=NULL,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (cid,),
                )

                try:
                    enable_and_run_task_by_name("send_comm_campaigns")
                except Exception:
                    logger.exception("Unable to start test campaign delivery | campaign_id=%s", cid)
                    flash(t("comm_campaign_send_failed"), "error")
                    return redirect(url_for("communications_campaigns_page", load=cid))

                flash(t("comm_test_campaign_queued"), "success")
                return redirect(url_for("communications_campaigns_page", load=cid))

            queue_result = queue_campaign_delivery(
                db,
                cid,
                rebuild_queue=((campaign.get("status") or "").strip().lower() != "sending"),
            )

            add_log(
                "info",
                "communications",
                "Campaign queued",
                {
                    "campaign_id": cid,
                    "queued_targets": queue_result.get("targets_inserted", 0),
                    "targets_total": queue_result.get("targets_total", 0),
                    "task_enqueued": queue_result.get("task_enqueued", False),
                    "reason": queue_result.get("reason"),
                    "trigger_provider": campaign.get("trigger_provider"),
                    "subscription_scope": campaign.get("subscription_scope"),
                    "subscription_template_id": campaign.get("subscription_template_id"),
                    "attachments": [a.get("filename") for a in (attachments or [])],
                },
            )

            if not queue_result.get("ok"):
                flash(t("comm_campaign_send_failed"), "error")
                return redirect(url_for("communications_campaigns_page", load=cid))

            flash(
                t("comm_campaign_queued_summary").format(
                    ok=queue_result.get("targets_total", 0),
                    failed=0,
                ),
                "success",
            )
            return redirect(url_for("communications_campaigns_page", load=cid))

        flash(t("comm_not_found"), "error")
        return redirect(url_for("communications_campaigns_page"))

    @app.route("/communications/campaigns", methods=["GET"])
    def communications_campaigns_page():
        data = load_campaign_page_data(
            get_db(),
            request.args.get("load", type=int),
            COMM_CAMPAIGN_EDITOR_COLUMNS,
            COMM_CAMPAIGN_LIST_COLUMNS,
        )
        return render_template(
            "communications/communications_campaigns.html",
            **data,
            current_subpage="campaigns",
        )


    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    @app.route("/communications/templates/action", methods=["POST"])
    def communications_templates_action():
        db = get_db()

        settings_row = db.query_one(f"SELECT {COMM_TRANSLATION_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
        settings = dict(settings_row) if settings_row else {}
        t = get_translator(settings)

        action = (request.form.get("action") or "").strip().lower()
        selected_language = _selected_template_language(settings)

        # Create
        if action == "create":
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            enabled = 1 if request.form.get("enabled") == "1" else 0

            key = _sanitize_key(request.form.get("key") or "")
            if not key:
                base = _sanitize_key(name) or "template"
                key = base
                n = 2
                while db.query_one("SELECT 1 FROM comm_templates WHERE key = ?", (key,)):
                    key = f"{base}_{n}"
                    n += 1
            rules = normalize_template_rules(db, request.form)
            trigger_event = rules["trigger_event"]
            trigger_provider = rules["trigger_provider"]
            expiration_change_direction = rules["expiration_change_direction"]
            subscription_scope = rules["subscription_scope"]
            subscription_template_id = rules["subscription_template_id"]
            days_before = rules["days_before"]
            days_after = rules["days_after"]

            if not key or not name or not subject or not body:
                flash(t("comm_missing_fields"), "error")
                return redirect(url_for("communications_templates_page"))

            exists = db.query_one("SELECT 1 FROM comm_templates WHERE key = ?", (key,))
            if exists:
                flash(t("comm_template_key_exists"), "error")
                return redirect(url_for("communications_templates_page"))

            duplicate = None


            if enabled:
                duplicate = find_enabled_template_duplicate(
                    db,
                    trigger_event=trigger_event,
                    trigger_provider=trigger_provider,
                    subscription_scope=subscription_scope,
                    subscription_template_id=subscription_template_id,
                    days_before=days_before,
                    days_after=days_after,
                    expiration_change_direction=expiration_change_direction,
                )
                if duplicate:
                    flash(
                        f"{t('comm_template_duplicate_enabled')} #{duplicate['id']} - {duplicate['name']}",
                        "error",
                    )
                    return redirect(url_for("communications_templates_page"))

            cur = db.execute(
                """
                INSERT INTO comm_templates(
                    key, name, enabled,
                    trigger_event, trigger_provider, expiration_change_direction,
                    subscription_scope, subscription_template_id,
                    days_before, days_after,
                    subject, body,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    key, name, enabled,
                    trigger_event, trigger_provider, expiration_change_direction,
                    subscription_scope, subscription_template_id,
                    days_before, days_after,
                    subject, body,
                ),
            )
            tid = getattr(cur, "lastrowid", None)
            _upsert_template_translation(db, int(tid), selected_language, subject, body)

            store_communication_attachments(db, "template", int(tid), request.files.getlist("attachments"))

            add_log(
                "info",
                "communications",
                "Template created",
                {
                    "id": tid,
                    "key": key,
                    "auto_disabled_duplicate": bool(duplicate),
                    "duplicate_template_id": duplicate.get("id") if duplicate else None,
                },
            )

            flash(t("comm_template_created"), "success")



            return redirect(url_for("communications_templates_page", load=tid, language=selected_language))

        # Save
        if action == "save":
            tid = request.form.get("template_id", type=int)
            if not tid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))

            existing = db.query_one(f"SELECT {COMM_TEMPLATE_EDITOR_COLUMNS} FROM comm_templates WHERE id = ?", (tid,))
            if not existing:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))

            existing = dict(existing)

            settings = db.query_one("SELECT expiry_mode, communication_language FROM settings WHERE id = 1")
            settings = dict(settings) if settings else {}

            is_stream_blocked = is_stream_blocked_template(existing)
            stream_blocked_required = (
                is_stream_blocked
                and subscription_expired_warning_requires_stream_blocked(settings)
            )

            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            enabled = 1 if request.form.get("enabled") == "1" else 0

            if stream_blocked_required:
                enabled = 1

            key = _sanitize_key(request.form.get("key") or existing.get("key") or "")
            if not key:
                key = existing.get("key") or ""
            rules = normalize_template_rules(db, request.form)
            trigger_event = rules["trigger_event"]
            trigger_provider = rules["trigger_provider"]
            expiration_change_direction = rules["expiration_change_direction"]
            subscription_scope = rules["subscription_scope"]
            subscription_template_id = rules["subscription_template_id"]
            days_before = rules["days_before"]
            days_after = rules["days_after"]

            if is_stream_blocked:
                key = "stream_blocked"
                trigger_event = "stream_blocked"
                trigger_provider = "all"
                expiration_change_direction = "all"
                subscription_scope = "all"
                subscription_template_id = None
                days_before = None
                days_after = 0

            if not key or not name or not subject or not body:
                flash(t("comm_missing_fields"), "error")
                return redirect(url_for("communications_templates_page", load=tid, language=selected_language))

            exists = db.query_one(
                "SELECT 1 FROM comm_templates WHERE key = ? AND id <> ?",
                (key, tid),
            )
            if exists:
                flash(t("comm_template_key_exists"), "error")
                return redirect(url_for("communications_templates_page", load=tid, language=selected_language))

            duplicate = None


            if enabled:
                duplicate = find_enabled_template_duplicate(
                    db,
                    trigger_event=trigger_event,
                    trigger_provider=trigger_provider,
                    subscription_scope=subscription_scope,
                    subscription_template_id=subscription_template_id,
                    days_before=days_before,
                    days_after=days_after,
                    expiration_change_direction=expiration_change_direction,
                    exclude_id=tid,
                )
                if duplicate:
                    flash(
                        f"{t('comm_template_duplicate_enabled')} #{duplicate['id']} - {duplicate['name']}",
                        "error",
                    )
                    return redirect(url_for("communications_templates_page", load=tid, language=selected_language))

            legacy_subject = subject if selected_language == "en" else (existing.get("subject") or subject)
            legacy_body = body if selected_language == "en" else (existing.get("body") or body)
            db.execute(
                """
                UPDATE comm_templates
                SET key=?, name=?, enabled=?,
                    trigger_event=?, trigger_provider=?, expiration_change_direction=?,
                    subscription_scope=?, subscription_template_id=?,
                    days_before=?, days_after=?,
                    subject=?, body=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    key, name, enabled,
                    trigger_event, trigger_provider, expiration_change_direction,
                    subscription_scope, subscription_template_id,
                    days_before, days_after,
                    legacy_subject, legacy_body,
                    tid,
                ),
            )
            _upsert_template_translation(db, int(tid), selected_language, subject, body)

            store_communication_attachments(db, "template", int(tid), request.files.getlist("attachments"))

            add_log(
                "info",
                "communications",
                "Template updated",
                {
                    "id": tid,
                    "auto_disabled_duplicate": bool(duplicate),
                    "duplicate_template_id": duplicate.get("id") if duplicate else None,
                },
            )

            flash(t("comm_template_saved"), "success")



            return redirect(url_for("communications_templates_page", load=tid, language=selected_language))

        # Delete
        if action == "delete":
            tid = request.form.get("template_id", type=int)
            if not tid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))

            existing = db.query_one("SELECT key FROM comm_templates WHERE id = ?", (tid,))
            existing = dict(existing) if existing else None

            if is_stream_blocked_template(existing):
                flash(t("comm_stream_blocked_template_locked"), "error")
                return redirect(url_for("communications_templates_page", load=tid, language=selected_language))

            db.execute("DELETE FROM comm_templates WHERE id = ?", (tid,))
            add_log("info", "communications", "Template deleted", {"id": tid})
            flash(t("comm_template_deleted"), "success")
            return redirect(url_for("communications_templates_page"))

        flash(t("comm_not_found"), "error")
        return redirect(url_for("communications_templates_page"))


    @app.post("/communications/templates/restore-defaults")
    def communications_templates_restore_defaults():
        db = get_db()

        settings_row = db.query_one(f"SELECT {COMM_TRANSLATION_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
        settings = dict(settings_row) if settings_row else {}
        t = get_translator(settings)

        restored = restore_default_comm_templates(db)

        add_log("info", "communications", "Default communication templates restored", {"restored": restored})
        flash(t("comm_templates_defaults_restored"), "success")
        return redirect(url_for("communications_templates_page"))


    @app.route("/communications/templates", methods=["GET"])
    def communications_templates_page():
        db = get_db()
        page = max(_as_int(request.args.get("page"), 1), 1)
        per_page = _as_int(request.args.get("per_page"), 20)
        if per_page not in (20, 50, 100):
            per_page = 20
        settings = db.query_one("SELECT expiry_mode, communication_language FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        selected_language = _selected_template_language(settings)
        data = load_template_page_data(
            db,
            load_id=request.args.get("load", type=int),
            page=page,
            per_page=per_page,
            language=selected_language,
            editor_columns=COMM_TEMPLATE_EDITOR_COLUMNS,
            list_columns=COMM_TEMPLATE_LIST_COLUMNS,
        )
        return render_template(
            "communications/communications_templates.html",
            **data,
            current_subpage="templates",
            stream_blocked_required=subscription_expired_warning_requires_stream_blocked(settings),
            selected_language=selected_language,
        )


    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @app.route("/communications/configuration/action", methods=["POST"])
    def communications_configuration_action():
        db = get_db()
        t = get_translator()

        settings = db.query_one(f"SELECT {COMM_CONFIG_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        action = (request.form.get("action") or "").strip()

        # Auto-save (used by the unified config form)
        if action == "save_all":
            values = parse_communication_configuration(request.form, settings)


            db.execute(
                """
                UPDATE settings SET
                  mailing_enabled=?,
                  skip_never_used_accounts=?,
                  mail_from=?,
                  smtp_host=?,
                  smtp_port=?,
                  smtp_tls=?,
                  smtp_user=?,
                  smtp_pass=?,
                  smtp_auth_method=?,
                  smtp_oauth_access_token=?,
                  discord_enabled=?,
                  discord_bot_token=?,
                  notifications_send_mode=?,
                  notifications_order=?,
                  user_notifications_can_override=?,
                  communication_language=?
                WHERE id=1
                """,
                tuple(values[key] for key in (
                    "mailing_enabled", "skip_never_used_accounts", "mail_from",
                    "smtp_host", "smtp_port", "smtp_tls", "smtp_user", "smtp_pass",
                    "smtp_auth_method", "smtp_oauth_access_token", "discord_enabled",
                    "discord_bot_token", "notifications_send_mode", "notifications_order",
                    "user_notifications_can_override", "communication_language",
                )),
            )

            add_log("info", "communications", "Communication settings updated")
            flash(t("comm_config_saved"), "success")
            return redirect(url_for("communications_configuration_page"))

        if action == "test_email":
            test_settings = db.query_one(
                f"SELECT {COMM_CONFIG_SETTINGS_COLUMNS}, admin_email, contact_email FROM settings WHERE id = 1"
            )
            test_settings = dict(test_settings) if test_settings else {}
            to_email = (
                (test_settings.get("contact_email") or "").strip()
                or (test_settings.get("admin_email") or "").strip()
                or (test_settings.get("mail_from") or "").strip()
            )
            if not to_email:
                flash(t("comm_test_failed").format(error=t("comm_missing_admin_email_short")), "error")
                return redirect(url_for("communications_configuration_page"))

            ok, error = send_email(
                t("comm_test_email_subject"),
                t("comm_test_email_body"),
                to_email,
                test_settings,
            )
            if ok:
                flash(t("comm_test_ok"), "success")
            else:
                flash(t("comm_test_failed").format(error=error or t("comm_email_send_failed_short")), "error")
            return redirect(url_for("communications_configuration_page"))

        if action == "test_discord":
            token = (request.form.get("discord_bot_token") or "").strip()
            if not token:
                try:
                    token = (decrypt_secret(settings.get("discord_bot_token")) or "").strip()
                except Exception as e:
                    logger.exception("Unable to decrypt Discord token for connection test")
                    flash(t("comm_test_failed").format(error=str(e)), "error")
                    return redirect(url_for("communications_configuration_page"))
            ok, detail = validate_discord_bot_token(token)
            if ok:
                flash(t("comm_test_ok"), "success")
            else:
                flash(t("comm_test_failed").format(error=detail), "error")
            return redirect(url_for("communications_configuration_page"))
        # Queue retry of failed scheduled communications
        if action == "retry_scheduled_errors":
            try:
                retried = retry_failed_scheduled_communications(db)
                try:
                    enable_and_run_task_by_name("send_expiration_emails")
                except Exception:
                    logger.exception(
                        "Scheduled communications were requeued but task startup failed | retried=%s",
                        retried,
                    )

                add_log("info", "communications", f"{retried} scheduled communication error(s) requeued")
                flash(t("comm_retry_scheduled_success"), "success")
            except Exception as e:
                logger.exception("Unable to retry failed scheduled communications")
                flash(f"{t('comm_retry_scheduled_error')}: {e}", "error")

            return redirect(url_for("communications_configuration_page"))

        flash(t("comm_not_found"), "error")
        return redirect(url_for("communications_configuration_page"))


    @app.route("/communications/configuration", methods=["GET"])
    def communications_configuration_page():
        data = load_configuration_page_data(get_db(), COMM_CONFIG_SETTINGS_COLUMNS)
        return render_template(
            "communications/communications_configuration.html",
            **data,
            current_subpage="configuration",
            communication_languages=communication_language_options(),
        )
