# Unified Communications UI (Email + Discord)

import json
from flask import render_template, request, redirect, url_for, flash, jsonify
from mailing_utils import build_user_context, render_mail

from core.i18n import get_translator
from core.communication_i18n import communication_language_options, normalize_communication_language
from core.smtp_settings import normalize_smtp_auth_method
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
from notifications_utils import parse_notifications_order
from secret_store import encrypt_secret, decrypt_secret

from communications_engine import (
    store_uploads,
    fetch_template_attachments,
    fetch_campaign_attachments,
    queue_campaign_delivery,
)
from tasks_engine import enable_and_run_task_by_name


def _as_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default


def _sanitize_key(raw: str) -> str:
    raw = (raw or "").strip().lower()
    raw = raw.replace(" ", "_")
    # keep only a-z 0-9 _ -
    out = []
    for ch in raw:
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
    return "".join(out)


def _sanitize_notifications_order(raw: str) -> str:
    # reuse existing helper semantics: only email/discord, preserve order, unique
    parts = parse_notifications_order(raw)
    if not parts:
        return "email"
    return ",".join(parts)




def _encrypted_secret_from_form(raw_value, existing_value, *, empty_existing=None):
    if raw_value is None or not str(raw_value).strip():
        return existing_value if existing_value is not None else empty_existing
    return encrypt_secret(str(raw_value).strip())


def _selected_template_language(settings=None):
    raw = request.form.get("language") or request.args.get("language") or (settings or {}).get("communication_language") or "en"
    return normalize_communication_language(raw)


def _upsert_template_translation(db, template_id: int, language: str, subject: str, body: str) -> None:
    language = normalize_communication_language(language)
    db.execute(
        """
        INSERT INTO comm_template_translations(template_id, language, subject, body, created_at, updated_at)
        VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(template_id, language) DO UPDATE SET
            subject=excluded.subject,
            body=excluded.body,
            updated_at=CURRENT_TIMESTAMP
        """,
        (int(template_id), language, subject or "", body or ""),
    )


def _apply_template_translation(db, template: dict | None, language: str) -> dict | None:
    if not template:
        return template
    row = db.query_one(
        """
        SELECT subject, body
        FROM comm_template_translations
        WHERE template_id = ?
          AND language = ?
        LIMIT 1
        """,
        (int(template["id"]), normalize_communication_language(language)),
    )
    if row:
        row = dict(row)
        template["subject"] = row.get("subject") or ""
        template["body"] = row.get("body") or ""
    return template

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
COMM_HISTORY_COLUMNS = """
                h.kind,
                h.channel_used,
                h.status,
                h.error,
                h.sent_at,
                h.meta_json
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

            files = request.files.getlist("attachments")
            saved = store_uploads("campaign", int(cid), files)
            for att in saved:
                db.execute(
                    "INSERT INTO comm_campaign_attachments(campaign_id, filename, mime_type, path) VALUES(?,?,?,?)",
                    (cid, att["filename"], att.get("mime_type"), att["path"]),
                )

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

            files = request.files.getlist("attachments")
            saved = store_uploads("campaign", int(cid), files)
            for att in saved:
                db.execute(
                    "INSERT INTO comm_campaign_attachments(campaign_id, filename, mime_type, path) VALUES(?,?,?,?)",
                    (cid, att["filename"], att.get("mime_type"), att["path"]),
                )

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
        db = get_db()

        servers = db.query("SELECT id, name FROM servers ORDER BY name")

        subscription_templates = db.query(
            """
            SELECT id, name, is_default
            FROM subscription_templates
            WHERE COALESCE(is_enabled, 1) = 1
            ORDER BY is_default DESC, name ASC
            """
        ) or []

        load_id = request.args.get("load", type=int)
        loaded = None
        if load_id:
            loaded = db.query_one(f"SELECT {COMM_CAMPAIGN_EDITOR_COLUMNS} FROM comm_campaigns WHERE id = ?", (load_id,))
            loaded = dict(loaded) if loaded else None
            if loaded:
                loaded["attachments"] = fetch_campaign_attachments(db, int(loaded["id"]))

        campaigns = db.query(
            f"""
            SELECT
                {COMM_CAMPAIGN_LIST_COLUMNS},
                st.name AS subscription_template_name
            FROM comm_campaigns c
            LEFT JOIN subscription_templates st ON st.id = c.subscription_template_id
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT 200
            """
        )
        campaigns = [dict(r) for r in (campaigns or [])]

        return render_template(
            "communications/communications_campaigns.html",
            campaigns=campaigns,
            servers=servers,
            subscription_templates=subscription_templates,
            loaded_campaign=loaded,
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

            trigger_event = (request.form.get("trigger_event") or "expiration").strip().lower()
            if trigger_event not in ("expiration", "user_creation", "pending_invite_reminder", "referral_reward", "expiration_change", "stream_blocked", "usage_risk_upgrade_suggestion"):
                trigger_event = "expiration"

            trigger_provider = (request.form.get("trigger_provider") or "all").strip().lower()
            if trigger_provider not in ("all", "plex", "jellyfin"):
                trigger_provider = "all"

            expiration_change_direction = (request.form.get("expiration_change_direction") or "all").strip().lower()
            if expiration_change_direction not in ("all", "increase", "decrease"):
                expiration_change_direction = "all"

            if trigger_event != "expiration_change":
                expiration_change_direction = "all"

            subscription_scope_raw = (request.form.get("subscription_scope_value") or "none").strip()
            subscription_scope = "none"
            subscription_template_id = None

            if subscription_scope_raw == "all":
                subscription_scope = "all"
            elif subscription_scope_raw.startswith("subscription:"):
                sub_id_raw = subscription_scope_raw.split(":", 1)[1].strip()
                try:
                    subscription_template_id = int(sub_id_raw)
                except Exception:
                    subscription_template_id = None

                if subscription_template_id:
                    sub_exists = db.query_one(
                        """
                        SELECT id
                        FROM subscription_templates
                        WHERE id = ?
                          AND COALESCE(is_enabled, 1) = 1
                        """,
                        (subscription_template_id,),
                    )
                    if sub_exists:
                        subscription_scope = "specific"
                    else:
                        subscription_scope = "none"
                        subscription_template_id = None
                else:
                    subscription_scope = "none"
                    subscription_template_id = None

            days_after_raw = (request.form.get("days_after") or "").strip()
            days_after = None
            if days_after_raw != "":
                try:
                    days_after = int(days_after_raw)
                except Exception:
                    days_after = None

            days_before_raw = (request.form.get("days_before") or "").strip()
            days_before = None
            if days_before_raw != "":
                try:
                    days_before = int(days_before_raw)
                except Exception:
                    days_before = None

            delay_direction = (request.form.get("delay_direction") or "").strip().lower()
            if delay_direction not in ("before", "after"):
                delay_direction = "before"

            if isinstance(days_before, int) and days_before < 0:
                days_before = 0
            if isinstance(days_after, int) and days_after < 0:
                days_after = 0

            if trigger_event in ("user_creation", "pending_invite_reminder"):
                days_before = None
                if days_after is None:
                    days_after = 0
                delay_direction = "after"
            elif trigger_event in ("referral_reward", "expiration_change", "stream_blocked", "usage_risk_upgrade_suggestion"):
                days_before = None
                days_after = 0
                delay_direction = "after"
            else:
                if delay_direction == "after":
                    offset = days_after if days_after is not None else (days_before if days_before is not None else 0)
                    days_after = offset
                    days_before = None
                else:
                    offset = days_before if days_before is not None else (days_after if days_after is not None else 0)
                    days_before = offset
                    days_after = None

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

            files = request.files.getlist("attachments")
            saved = store_uploads("template", int(tid), files)
            for att in saved:
                db.execute(
                    "INSERT INTO comm_template_attachments(template_id, filename, mime_type, path) VALUES(?,?,?,?)",
                    (tid, att["filename"], att.get("mime_type"), att["path"]),
                )

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

            trigger_event = (request.form.get("trigger_event") or "expiration").strip().lower()
            if trigger_event not in ("expiration", "user_creation", "pending_invite_reminder", "referral_reward", "expiration_change", "stream_blocked", "usage_risk_upgrade_suggestion"):
                trigger_event = "expiration"

            trigger_provider = (request.form.get("trigger_provider") or "all").strip().lower()
            if trigger_provider not in ("all", "plex", "jellyfin"):
                trigger_provider = "all"

            expiration_change_direction = (request.form.get("expiration_change_direction") or "all").strip().lower()
            if expiration_change_direction not in ("all", "increase", "decrease"):
                expiration_change_direction = "all"

            if trigger_event != "expiration_change":
                expiration_change_direction = "all"

            subscription_scope_raw = (request.form.get("subscription_scope_value") or "none").strip()
            subscription_scope = "none"
            subscription_template_id = None

            if subscription_scope_raw == "all":
                subscription_scope = "all"
            elif subscription_scope_raw.startswith("subscription:"):
                sub_id_raw = subscription_scope_raw.split(":", 1)[1].strip()
                try:
                    subscription_template_id = int(sub_id_raw)
                except Exception:
                    subscription_template_id = None

                if subscription_template_id:
                    sub_exists = db.query_one(
                        """
                        SELECT id
                        FROM subscription_templates
                        WHERE id = ?
                          AND COALESCE(is_enabled, 1) = 1
                        """,
                        (subscription_template_id,),
                    )
                    if sub_exists:
                        subscription_scope = "specific"
                    else:
                        subscription_scope = "none"
                        subscription_template_id = None
                else:
                    subscription_scope = "none"
                    subscription_template_id = None

            days_after_raw = (request.form.get("days_after") or "").strip()
            days_after = None
            if days_after_raw != "":
                try:
                    days_after = int(days_after_raw)
                except Exception:
                    days_after = None

            days_before_raw = (request.form.get("days_before") or "").strip()
            days_before = None
            if days_before_raw != "":
                try:
                    days_before = int(days_before_raw)
                except Exception:
                    days_before = None

            delay_direction = (request.form.get("delay_direction") or "").strip().lower()
            if delay_direction not in ("before", "after"):
                delay_direction = "before"

            if isinstance(days_before, int) and days_before < 0:
                days_before = 0
            if isinstance(days_after, int) and days_after < 0:
                days_after = 0

            if trigger_event in ("user_creation", "pending_invite_reminder"):
                days_before = None
                if days_after is None:
                    days_after = 0
                delay_direction = "after"
            elif trigger_event in ("referral_reward", "expiration_change", "stream_blocked", "usage_risk_upgrade_suggestion"):
                days_before = None
                days_after = 0
                delay_direction = "after"
            else:
                if delay_direction == "after":
                    offset = days_after if days_after is not None else (days_before if days_before is not None else 0)
                    days_after = offset
                    days_before = None
                else:
                    offset = days_before if days_before is not None else (days_after if days_after is not None else 0)
                    days_before = offset
                    days_after = None

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

            files = request.files.getlist("attachments")
            saved = store_uploads("template", int(tid), files)
            for att in saved:
                db.execute(
                    "INSERT INTO comm_template_attachments(template_id, filename, mime_type, path) VALUES(?,?,?,?)",
                    (tid, att["filename"], att.get("mime_type"), att["path"]),
                )

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

        load_id = request.args.get("load", type=int)
        #duplicate_disabled = request.args.get("duplicate_disabled", type=int) == 1
        #duplicate_disabled_reason = (request.args.get("duplicate_disabled_reason") or "").strip()

        settings = db.query_one("SELECT expiry_mode, communication_language FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        selected_language = _selected_template_language(settings)

        loaded = None
        loaded_is_stream_blocked = False
        stream_blocked_required = subscription_expired_warning_requires_stream_blocked(settings)

        if load_id:
            loaded = db.query_one(f"SELECT {COMM_TEMPLATE_EDITOR_COLUMNS} FROM comm_templates WHERE id = ?", (load_id,))
            loaded = dict(loaded) if loaded else None
            if loaded:
                loaded = _apply_template_translation(db, loaded, selected_language)
                loaded["attachments"] = fetch_template_attachments(db, int(loaded["id"]))
                loaded_is_stream_blocked = is_stream_blocked_template(loaded)

        templates = db.query(f"""
            SELECT
              {COMM_TEMPLATE_LIST_COLUMNS},
              st.name AS subscription_template_name
            FROM comm_templates ct
            LEFT JOIN comm_template_translations ctl ON ctl.template_id = ct.id AND ctl.language = ?
            LEFT JOIN subscription_templates st ON st.id = ct.subscription_template_id
            ORDER BY ct.enabled DESC, LOWER(ct.name), ct.id DESC
        """, (selected_language,))
        templates = [dict(r) for r in (templates or [])]

        subscription_templates = db.query(
            """
            SELECT id, name
            FROM subscription_templates
            WHERE COALESCE(is_enabled, 1) = 1
            ORDER BY name COLLATE NOCASE
            """
        ) or []
        subscription_templates = [dict(r) for r in subscription_templates]

        return render_template(
            "communications/communications_templates.html",
            templates=templates,
            loaded_template=loaded,
            subscription_templates=subscription_templates,
            current_subpage="templates",
            #duplicate_disabled=duplicate_disabled,
            #duplicate_disabled_reason=duplicate_disabled_reason,
            loaded_is_stream_blocked=loaded_is_stream_blocked,
            stream_blocked_required=stream_blocked_required,
            selected_language=selected_language,
        )


    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    @app.route("/communications/history")
    def communications_history_page():
        db = get_db()

        page = max(_as_int(request.args.get("page"), 1), 1)
        per_page = 20

        sort = (request.args.get("sort") or "sent_at").strip().lower()
        order = (request.args.get("order") or "").strip().lower()

        if sort == "sent_at" and not order:
            order = "desc"

        if order not in ("asc", "desc"):
            order = "asc"

        if sort == "sent_at" and order == "asc" and not request.args.get("order"):
            order = "desc"

        trigger_filter = (request.args.get("trigger") or "").strip().lower()
        trigger_options = [
            ("", "All communications"),
            ("usage_risk_upgrade_suggestion", "Upgrade suggestions"),
            ("stream_blocked", "Stream blocked"),
            ("expiration", "Expiration"),
            ("expiration_change", "Expiration changes"),
            ("user_creation", "User creation"),
            ("pending_invite_reminder", "Pending invites"),
            ("referral_reward", "Referral rewards"),
        ]
        allowed_triggers = {value for value, _label in trigger_options if value}
        if trigger_filter not in allowed_triggers:
            trigger_filter = ""

        sent_at_sort_expr = """
            COALESCE(
                CASE
                    WHEN typeof(h.sent_at) = 'integer' THEN h.sent_at
                    WHEN typeof(h.sent_at) = 'text' AND h.sent_at GLOB '[0-9][0-9][0-9][0-9]-*' THEN CAST(strftime('%s', h.sent_at) AS INTEGER)
                    WHEN typeof(h.sent_at) = 'text' AND h.sent_at GLOB '[0-9]*' THEN CAST(h.sent_at AS INTEGER)
                    ELSE CAST(strftime('%s', h.sent_at) AS INTEGER)
                END,
                0
            )
        """

        sort_map = {
            "kind": "LOWER(COALESCE(h.kind, ''))",
            "user": "LOWER(COALESCE(u.username, ''))",
            "channel_used": "LOWER(COALESCE(h.channel_used, ''))",
            "status": "LOWER(COALESCE(h.status, ''))",
            "error": "LOWER(COALESCE(h.error, ''))",
            "sent_at": sent_at_sort_expr,
        }

        if sort not in sort_map:
            sort = "sent_at"

        order_sql = "ASC" if order == "asc" else "DESC"
        order_by_sql = f"{sort_map[sort]} {order_sql}, h.id DESC"

        history_where = []
        history_params = []
        if trigger_filter:
            history_where.append("(t.trigger_event = ? OR h.meta_json LIKE ?)")
            history_params.extend([trigger_filter, f"%{trigger_filter}%"])
        history_where_sql = f"WHERE {' AND '.join(history_where)}" if history_where else ""

        total_row = db.query_one(
            f"""
            SELECT COUNT(*) AS total
            FROM comm_history h
            LEFT JOIN comm_templates t ON t.id = h.template_id
            {history_where_sql}
            """,
            tuple(history_params),
        )
        total_rows = int(total_row["total"]) if total_row and total_row["total"] is not None else 0
        total_pages = max((total_rows + per_page - 1) // per_page, 1)

        summary_row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN channel_used='email' AND status='sent' THEN 1 ELSE 0 END) AS email_sent,
              SUM(CASE WHEN channel_used='email' AND status='failed' THEN 1 ELSE 0 END) AS email_failed,
              SUM(CASE WHEN channel_used='discord' AND status='sent' THEN 1 ELSE 0 END) AS discord_sent,
              SUM(CASE WHEN channel_used='discord' AND status='failed' THEN 1 ELSE 0 END) AS discord_failed,
              SUM(CASE WHEN status='sent' AND datetime(sent_at) >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) AS sent_24h,
              SUM(CASE WHEN status='failed' AND datetime(sent_at) >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) AS failed_24h
            FROM comm_history
            """
        ) or {}
        communication_summary = dict(summary_row)
        queue_row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM comm_scheduled
            """
        ) or {}
        communication_summary.update(dict(queue_row))
        communication_summary = {
            key: int(value or 0)
            for key, value in communication_summary.items()
        }

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * per_page

        settings_row = db.query_one("SELECT brand_name FROM settings WHERE id = 1")
        settings = dict(settings_row) if settings_row else {}
        brand_name = settings.get("brand_name") or "VODUM"

        rows = db.query(
            f"""
            SELECT
                {COMM_HISTORY_COLUMNS},
                u.id AS user_id,
                u.username AS user_username,
                u.firstname AS user_firstname,
                u.lastname AS user_lastname,
                u.email AS user_email,
                u.expiration_date AS user_expiration_date,
                u.subscription_template_id AS user_subscription_template_id,
                st.name AS subscription_name,
                st.duration_days AS subscription_duration_days,
                st.subscription_value AS subscription_value,
                t.key AS template_key,
                t.subject AS template_subject,
                t.body AS template_body,
                c.name AS campaign_name,
                c.subject AS campaign_subject,
                c.body AS campaign_body
            FROM comm_history h
            LEFT JOIN vodum_users u ON u.id = h.user_id
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            LEFT JOIN comm_templates t ON t.id = h.template_id
            LEFT JOIN comm_campaigns c ON c.id = h.campaign_id
            {history_where_sql}
            ORDER BY {order_by_sql}
            LIMIT ? OFFSET ?
            """,
            (*history_params, per_page, offset),
        )

        def _render_history_message(row):
            meta = {}
            try:
                meta = json.loads(row.get("meta_json") or "{}")
            except Exception:
                meta = {}

            if meta.get("rendered_subject") or meta.get("rendered_body"):
                row["rendered_subject"] = meta.get("rendered_subject") or ""
                row["rendered_body"] = meta.get("rendered_body") or ""
                return row

            payload = meta.get("payload") or {}

            context_input = {
                "id": row.get("user_id"),
                "username": row.get("user_username") or "",
                "firstname": row.get("user_firstname") or "",
                "lastname": row.get("user_lastname") or "",
                "email": row.get("user_email") or "",
                "expiration_date": row.get("user_expiration_date") or "",
                "subscription_template_id": row.get("user_subscription_template_id"),
                "subscription_name": row.get("subscription_name") or "",
                "subscription_duration_days": row.get("subscription_duration_days") or "",
                "subscription_value": row.get("subscription_value") or "",
                "brand_name": brand_name,
            }

            context_input.update(meta)
            context_input.update(payload)
            context_input["brand_name"] = meta.get("brand_name") or payload.get("brand_name") or brand_name

            context = build_user_context(context_input)

            for key, value in context_input.items():
                if value not in (None, ""):
                    context[key] = str(value)

            subject = row.get("template_subject") if row.get("kind") == "template" else row.get("campaign_subject")
            body = row.get("template_body") if row.get("kind") == "template" else row.get("campaign_body")

            row["rendered_subject"] = render_mail(subject or "", context)
            row["rendered_body"] = render_mail(body or "", context)

            return row

        history = [_render_history_message(dict(r)) for r in (rows or [])]

        scheduled_where = "AND t.trigger_event = ?" if trigger_filter else ""
        scheduled_params = (trigger_filter,) if trigger_filter else ()

        scheduled_rows = db.query(
            f"""
            SELECT
              q.id,
              q.status,
              q.send_at,
              q.next_attempt_at,
              q.last_attempt_at,
              q.attempt_count,
              q.max_attempts,
              q.last_error,
              q.channels_sent,
              q.dedupe_key,
              q.updated_at,
              q.payload_json,
              t.id AS template_id,
              t.key AS template_key,
              t.subject AS template_subject,
              t.body AS template_body,
              t.trigger_event,
              u.id AS user_id,
              u.username AS user_username,
              u.firstname AS user_firstname,
              u.lastname AS user_lastname,
              u.email AS user_email,
              u.expiration_date AS user_expiration_date,
              u.subscription_template_id AS user_subscription_template_id,
              st.name AS subscription_name,
              st.duration_days AS subscription_duration_days,
              st.subscription_value AS subscription_value
            FROM comm_scheduled q
            JOIN comm_templates t ON t.id = q.template_id
            LEFT JOIN vodum_users u ON u.id = q.vodum_user_id
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            WHERE q.status IN ('pending', 'error')
              {scheduled_where}
            ORDER BY
              CASE q.status WHEN 'error' THEN 0 ELSE 1 END,
              datetime(COALESCE(q.next_attempt_at, q.send_at, q.updated_at)) ASC,
              q.id ASC
            LIMIT 25
            """,
            scheduled_params,
        ) or []

        scheduled_history = []
        for r in scheduled_rows:
            r = dict(r)
            payload = {}
            try:
                payload = json.loads(r.get("payload_json") or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            meta = {
                "scheduled_id": r.get("id"),
                "template_key": r.get("template_key"),
                "trigger_event": r.get("trigger_event"),
                "payload": payload,
                "dedupe_key": r.get("dedupe_key"),
                "attempt_count": r.get("attempt_count") or 0,
                "max_attempts": r.get("max_attempts") or 10,
                "next_attempt_at": r.get("next_attempt_at"),
            }
            row = {
                "id": f"scheduled-{r.get('id')}",
                "kind": "template",
                "is_scheduled": True,
                "template_id": r.get("template_id"),
                "campaign_id": None,
                "user_id": r.get("user_id"),
                "user_username": r.get("user_username"),
                "user_firstname": r.get("user_firstname"),
                "user_lastname": r.get("user_lastname"),
                "user_email": r.get("user_email"),
                "user_expiration_date": r.get("user_expiration_date"),
                "user_subscription_template_id": r.get("user_subscription_template_id"),
                "subscription_name": r.get("subscription_name"),
                "subscription_duration_days": r.get("subscription_duration_days"),
                "subscription_value": r.get("subscription_value"),
                "template_key": r.get("template_key"),
                "template_subject": r.get("template_subject"),
                "template_body": r.get("template_body"),
                "campaign_name": None,
                "campaign_subject": None,
                "campaign_body": None,
                "channel_used": r.get("channels_sent") or "",
                "status": r.get("status") or "pending",
                "error": r.get("last_error") or r.get("dedupe_key") or "",
                "sent_at": r.get("last_attempt_at") or r.get("send_at"),
                "send_at": r.get("send_at"),
                "next_attempt_at": r.get("next_attempt_at"),
                "attempt_count": r.get("attempt_count") or 0,
                "max_attempts": r.get("max_attempts") or 10,
                "meta_json": json.dumps(meta, ensure_ascii=False),
            }
            scheduled_history.append(_render_history_message(row))

        if page == 1:
            history = scheduled_history + history

        return render_template(
            "communications/communications_history.html",
            history=history,
            current_subpage="history",
            page=page,
            per_page=per_page,
            total_rows=total_rows,
            total_pages=total_pages,
            sort=sort,
            order=order,
            trigger_filter=trigger_filter,
            trigger_options=trigger_options,
            communication_summary=communication_summary,
        )


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
            # Email
            mailing_enabled = 1 if request.form.get("mailing_enabled") == "1" else 0
            skip_never_used_accounts = 1 if request.form.get("skip_never_used_accounts") == "1" else 0
            mail_from = (request.form.get("mail_from") or "").strip() or None
            smtp_host = (request.form.get("smtp_host") or "").strip() or None
            smtp_port = _as_int(request.form.get("smtp_port"), None)
            smtp_tls = 1 if request.form.get("smtp_tls") == "1" else 0
            smtp_user = (request.form.get("smtp_user") or "").strip() or None
            smtp_auth_method = (request.form.get("smtp_auth_method") or "password").strip().lower()
            if smtp_auth_method not in ("password", "oauth2"):
                smtp_auth_method = "password"

            # Safety: do not wipe secrets on auto-save if input is empty
            smtp_pass_raw = request.form.get("smtp_pass")
            smtp_pass = _encrypted_secret_from_form(
                smtp_pass_raw,
                settings.get("smtp_pass"),
                empty_existing="",
            )

            smtp_oauth_token_raw = request.form.get("smtp_oauth_access_token")
            smtp_oauth_access_token = _encrypted_secret_from_form(
                smtp_oauth_token_raw,
                settings.get("smtp_oauth_access_token"),
                empty_existing=None,
            )
            smtp_auth_method = normalize_smtp_auth_method(
                smtp_auth_method,
                settings,
                smtp_pass,
                smtp_oauth_access_token,
            )

            # Discord
            discord_enabled = 1 if request.form.get("discord_enabled") == "1" else 0
            discord_bot_token_raw = request.form.get("discord_bot_token")
            discord_bot_token = encrypt_secret(
                (discord_bot_token_raw or "").strip() or None
            )
            if discord_bot_token_raw is not None and discord_bot_token_raw.strip() == "":
                discord_bot_token = settings.get("discord_bot_token") or None

            # General
            send_mode = (request.form.get("notifications_send_mode") or settings.get("notifications_send_mode") or "first").strip().lower()
            if send_mode not in ("first", "all"):
                send_mode = "first"

            notifications_order = _sanitize_notifications_order(
                request.form.get("notifications_order") or settings.get("notifications_order") or "email"
            )
            user_can_override = 1 if request.form.get("user_notifications_can_override") == "1" else 0
            communication_language = normalize_communication_language(
                request.form.get("communication_language") or settings.get("communication_language") or "en"
            )

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
                (
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
                    send_mode,
                    notifications_order,
                    user_can_override,
                    communication_language,
                ),
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
                    pass

                add_log("info", "communications", f"{retried} scheduled communication error(s) requeued")
                flash(t("comm_retry_scheduled_success"), "success")
            except Exception as e:
                flash(f"{t('comm_retry_scheduled_error')}: {e}", "error")

            return redirect(url_for("communications_configuration_page"))

        flash(t("comm_not_found"), "error")
        return redirect(url_for("communications_configuration_page"))


    @app.route("/communications/configuration", methods=["GET"])
    def communications_configuration_page():
        db = get_db()

        settings = db.query_one(f"SELECT {COMM_CONFIG_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        settings["smtp_pass_configured"] = bool(settings.get("smtp_pass"))
        settings["smtp_oauth_access_token_configured"] = bool(settings.get("smtp_oauth_access_token"))
        settings["discord_bot_token_configured"] = bool(settings.get("discord_bot_token"))
        settings["smtp_pass"] = ""
        settings["smtp_oauth_access_token"] = ""
        settings["discord_bot_token"] = ""
        queue_row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM comm_scheduled
            """
        ) or {}
        queue_summary = {key: int(value or 0) for key, value in dict(queue_row).items()}
        return render_template(
            "communications/communications_configuration.html",
            settings=settings,
            current_subpage="configuration",
            communication_languages=communication_language_options(),
            queue_summary=queue_summary,
        )
