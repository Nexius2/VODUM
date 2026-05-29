# Unified Communications UI (Email + Discord)

import json
from flask import render_template, request, redirect, url_for, flash, jsonify

from core.i18n import get_translator
from web.helpers import get_db, add_log, send_email_via_settings
from discord_utils import validate_discord_bot_token
from notifications_utils import parse_notifications_order

from communications_engine import (
    store_uploads,
    fetch_template_attachments,
    fetch_campaign_attachments,
    available_channels,
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




def _find_enabled_template_duplicate(
    db,
    *,
    trigger_event: str,
    trigger_provider: str,
    subscription_scope: str,
    subscription_template_id,
    days_before,
    days_after,
    expiration_change_direction: str = "all",
    exclude_id: int | None = None,
):
    """
    Detect only true logical duplicates among ENABLED templates.

    Allowed:
    - same trigger/provider/subscription target with different delay slots
      (ex: J-30 / J-7 / J-0 for expiration)
    - all + plex/jellyfin fallback combinations
    - disabled duplicates

    Blocked:
    - another ENABLED template with the exact same logical slot
    """
    normalized_sub_id = subscription_template_id if subscription_scope == "specific" else None
    normalized_exp_dir = expiration_change_direction if trigger_event == "expiration_change" else "all"

    sql = """
        SELECT id, name
        FROM comm_templates
        WHERE enabled = 1
          AND trigger_event = ?
          AND trigger_provider = ?
          AND COALESCE(subscription_scope, 'none') = ?
          AND COALESCE(subscription_template_id, 0) = COALESCE(?, 0)
          AND COALESCE(expiration_change_direction, 'all') = ?
          AND (
                (days_before IS NULL AND ? IS NULL)
                OR days_before = ?
              )
          AND (
                (days_after IS NULL AND ? IS NULL)
                OR days_after = ?
              )
    """
    params = [
        trigger_event,
        trigger_provider,
        subscription_scope,
        normalized_sub_id,
        normalized_exp_dir,
        days_before, days_before,
        days_after, days_after,
    ]

    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)

    sql += " LIMIT 1"

    row = db.query_one(sql, tuple(params))
    return dict(row) if row else None

def _normalize_send_mode(settings: dict) -> str:
    mode = (settings or {}).get("notifications_send_mode")
    mode = (mode or "first").strip().lower()
    return mode if mode in ("first", "all") else "first"


def _campaign_attempts_satisfy_mode(db, settings: dict, user: dict, attempts: list) -> bool:
    """
    Campaign success rule:
    - FIRST: at least one successful channel
    - ALL  : all available channels for this user must succeed
    - skipped_only: treated as OK to stay aligned with unified comm engine behavior
    """
    mode = _normalize_send_mode(settings)
    avail = available_channels(db, settings, user)
    attempts = attempts or []

    sent_channels = {a.channel for a in attempts if getattr(a, "status", None) == "sent"}
    skipped_only = bool(attempts) and all(getattr(a, "status", None) == "skipped" for a in attempts)

    if skipped_only:
        return True

    if mode == "all":
        required = []
        if avail.get("email"):
            required.append("email")
        if avail.get("discord"):
            required.append("discord")

        if not required:
            return False

        return all(ch in sent_channels for ch in required)

    return any(getattr(a, "status", None) == "sent" for a in attempts)

DEFAULT_COMM_TEMPLATES = [
    {
        "key": "default_expiration_date_change",
        "name": "Expiration date change",
        "enabled": 0,
        "trigger_event": "expiration_change",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Your subscription date has been updated",
        "body": "Hello {username},\n\nYour subscription expiration date has been updated.\n\nPrevious expiration date: {old_expiration_date}\nNew expiration date: {new_expiration_date}\nChange: {expiration_change_signed_days} day(s)\nReason: {expiration_change_reason}\n\nBest regards,\nVODUM Team\n",
    },
    {
        "key": "default_fin",
        "name": "Expired subscription",
        "enabled": 0,
        "trigger_event": "expiration",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": 0,
        "days_after": None,
        "subject": "Your subscription has expired",
        "body": "Hello {username},\n\nYour subscription expired on {expiration_date}.\nYour access may now be suspended.\n\nIf you wish to continue using the service, please renew your subscription.\n\nBest regards,\nVODUM Team\n",
    },
    {
        "key": "default_pending_invite_reminder",
        "name": "Pending invite reminder",
        "enabled": 0,
        "trigger_event": "pending_invite_reminder",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 3,
        "subject": "Reminder - please accept your invitation",
        "body": "Hello {username},\n\nYour invitation is still waiting for acceptance.\n\nTo start using your account:\n- Open Plex or Jellyfin\n- Sign in with your account\n- Accept the library share invitation if prompted\n\nYour subscription expiration is currently set to: {expiration_date}\n\nBest regards,\nVODUM Team\n",
    },
    {
        "key": "default_preavis",
        "name": "Expiration notice",
        "enabled": 0,
        "trigger_event": "expiration",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": 30,
        "days_after": None,
        "subject": "Your subscription will expire in {days_left} days",
        "body": "Hello {username},\n\nYour subscription will expire in {days_left} days.\n\nExpiration date: {expiration_date}\n\nPlease renew it to avoid any service interruption.\n\nBest regards,\nVODUM Team\n",
    },
    {
        "key": "default_parrainage",
        "name": "Referral reward",
        "enabled": 0,
        "trigger_event": "referral_reward",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Referral reward granted",
        "body": "Hello {username},\n\nGood news: you earned {referral_reward_days} bonus day(s) thanks to {referred_username}.\n\nPrevious expiration date: {referrer_old_expiration_date}\nNew expiration date: {referrer_new_expiration_date}\n\nThank you for your referral.\n\nBest regards,\nVODUM Team\n",
    },
    {
        "key": "default_relance",
        "name": "Expiration reminder",
        "enabled": 0,
        "trigger_event": "expiration",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": 7,
        "days_after": None,
        "subject": "Reminder - your subscription will expire soon",
        "body": "Hello {username},\n\nThis is a friendly reminder that your subscription will expire in {days_left} days.\n\nExpiration date: {expiration_date}\n\nPlease renew it in time to avoid any service interruption.\n\nBest regards,\nVODUM Team\n",
    },
    {
        "key": "default_user_creation",
        "name": "User creation",
        "enabled": 0,
        "trigger_event": "user_creation",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Welcome - your account is ready",
        "body": "Hello {username},\n\nYour account has been created successfully.\n\nLogin email: {email}\n\nHow to get started:\n- Open Plex or Jellyfin\n- Sign in with your account\n- Accept the library share invitation if prompted\n\nSubscription expiration date: {expiration_date}\n\nBest regards,\nVODUM Team\n",
    },
]


def _restore_default_comm_templates(db) -> int:
    restored = 0

    for tpl in DEFAULT_COMM_TEMPLATES:
        restore_key = f"{tpl['key']}_restore_default"
        restore_name = f"{tpl['name']} - Default"

        existing = db.query_one(
            "SELECT id FROM comm_templates WHERE key = ?",
            (restore_key,),
        )

        if existing:
            continue

        db.execute(
            """
            INSERT INTO comm_templates(
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
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                restore_key,
                restore_name,
                0,
                tpl["trigger_event"],
                tpl["trigger_provider"],
                tpl["expiration_change_direction"],
                tpl["subscription_scope"],
                tpl["subscription_template_id"],
                tpl["days_before"],
                tpl["days_after"],
                tpl["subject"],
                tpl["body"],
            ),
        )

        restored += 1

    return restored

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

        # Create
        if action == "create":
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            raw_server_id = (request.form.get("server_id") or "").strip()
            server_id = _as_int(raw_server_id, None) if raw_server_id else None
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not name or not subject or not body:
                flash(t("comm_missing_fields"), "error")
                return redirect(url_for("communications_campaigns_page"))

            if server_id:
                exists = db.query_one("SELECT 1 FROM servers WHERE id = ?", (server_id,))
                if not exists:
                    server_id = None

            cur = db.execute(
                """
                INSERT INTO comm_campaigns(name, subject, body, server_id, status, is_test, created_at, updated_at)
                VALUES(?, ?, ?, ?, 'draft', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (name, subject, body, server_id, is_test),
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

        # Save
        if action == "save":
            cid = request.form.get("campaign_id", type=int)
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            raw_server_id = (request.form.get("server_id") or "").strip()
            server_id = _as_int(raw_server_id, None) if raw_server_id else None
            is_test = 1 if request.form.get("is_test") == "1" else 0

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
                SET name=?, subject=?, body=?, server_id=?, is_test=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (name, subject, body, server_id, is_test, cid),
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

        # Delete
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

        # Send
        if action == "send":
            cid = request.form.get("campaign_id", type=int)
            campaign = db.query_one("SELECT * FROM comm_campaigns WHERE id = ?", (cid,))
            if not campaign:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))
            campaign = dict(campaign)

            attachments = fetch_campaign_attachments(db, cid)

            users = db.query(
                """
                SELECT id, username, email, second_email, discord_user_id, notifications_order_override
                FROM vodum_users u
                WHERE EXISTS (SELECT 1 FROM media_users mu WHERE mu.vodum_user_id = u.id)
                """
            )

            server_id = campaign.get("server_id")
            if server_id:
                users = db.query(
                    """
                    SELECT u.id, u.username, u.email, u.second_email, u.discord_user_id, u.notifications_order_override
                    FROM vodum_users u
                    WHERE EXISTS (
                        SELECT 1 FROM media_users mu
                        WHERE mu.vodum_user_id = u.id AND mu.server_id = ?
                    )
                    """,
                    (server_id,),
                )

            if int(campaign.get("is_test") or 0) == 1:
                settings = db.query_one("SELECT * FROM settings WHERE id = 1")
                settings = dict(settings) if settings else {}

                admin_email = (settings.get("admin_email") or "").strip()
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

                flash("Test campaign queued.", "success")
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

        load_id = request.args.get("load", type=int)
        loaded = None
        if load_id:
            loaded = db.query_one("SELECT * FROM comm_campaigns WHERE id = ?", (load_id,))
            loaded = dict(loaded) if loaded else None
            if loaded:
                loaded["attachments"] = fetch_campaign_attachments(db, int(loaded["id"]))

        campaigns = db.query(
            "SELECT * FROM comm_campaigns ORDER BY created_at DESC, id DESC LIMIT 200"
        )
        campaigns = [dict(r) for r in (campaigns or [])]

        return render_template(
            "communications/communications_campaigns.html",
            campaigns=campaigns,
            servers=servers,
            loaded_campaign=loaded,
            current_subpage="campaigns",
        )


    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    @app.route("/communications/templates/action", methods=["POST"])
    def communications_templates_action():
        db = get_db()
        t = get_translator()

        action = (request.form.get("action") or "").strip().lower()

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
            if trigger_event not in ("expiration", "user_creation", "pending_invite_reminder", "referral_reward", "expiration_change"):
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
            elif trigger_event in ("referral_reward", "expiration_change"):
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
            duplicate_reason = ""

            if enabled:
                duplicate = _find_enabled_template_duplicate(
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
                    enabled = 0
                    duplicate_reason = f"#{duplicate['id']} - {duplicate['name']}"

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

            if duplicate:
                return redirect(
                    url_for(
                        "communications_templates_page",
                        load=tid,
                        duplicate_disabled=1,
                        duplicate_disabled_reason=duplicate_reason,
                    )
                )

            return redirect(url_for("communications_templates_page", load=tid))

        # Save
        if action == "save":
            tid = request.form.get("template_id", type=int)
            if not tid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))

            existing = db.query_one("SELECT * FROM comm_templates WHERE id = ?", (tid,))
            if not existing:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))

            existing = dict(existing)

            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            enabled = 1 if request.form.get("enabled") == "1" else 0

            key = _sanitize_key(request.form.get("key") or existing.get("key") or "")
            if not key:
                key = existing.get("key") or ""

            trigger_event = (request.form.get("trigger_event") or "expiration").strip().lower()
            if trigger_event not in ("expiration", "user_creation", "pending_invite_reminder", "referral_reward", "expiration_change"):
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
            elif trigger_event in ("referral_reward", "expiration_change"):
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
                return redirect(url_for("communications_templates_page", load=tid))

            exists = db.query_one(
                "SELECT 1 FROM comm_templates WHERE key = ? AND id <> ?",
                (key, tid),
            )
            if exists:
                flash(t("comm_template_key_exists"), "error")
                return redirect(url_for("communications_templates_page", load=tid))

            duplicate = None
            duplicate_reason = ""

            if enabled:
                duplicate = _find_enabled_template_duplicate(
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
                    enabled = 0
                    duplicate_reason = f"#{duplicate['id']} - {duplicate['name']}"

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
                    subject, body,
                    tid,
                ),
            )

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

            if duplicate:
                return redirect(
                    url_for(
                        "communications_templates_page",
                        load=tid,
                        duplicate_disabled=1,
                        duplicate_disabled_reason=duplicate_reason,
                    )
                )

            return redirect(url_for("communications_templates_page", load=tid))

        # Delete
        if action == "delete":
            tid = request.form.get("template_id", type=int)
            if not tid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))
            db.execute("DELETE FROM comm_templates WHERE id = ?", (tid,))
            add_log("info", "communications", "Template deleted", {"id": tid})
            flash(t("comm_template_deleted"), "success")
            return redirect(url_for("communications_templates_page"))

        flash(t("comm_not_found"), "error")
        return redirect(url_for("communications_templates_page"))


    @app.post("/communications/templates/restore-defaults")
    def communications_templates_restore_defaults():
        db = get_db()
        t = get_translator()

        restored = _restore_default_comm_templates(db)

        add_log("info", "communications", "Default communication templates restored", {"restored": restored})
        flash(t("comm_templates_defaults_restored"), "success")
        return redirect(url_for("communications_templates_page"))


    @app.route("/communications/templates", methods=["GET"])
    def communications_templates_page():
        db = get_db()

        load_id = request.args.get("load", type=int)
        duplicate_disabled = request.args.get("duplicate_disabled", type=int) == 1
        duplicate_disabled_reason = (request.args.get("duplicate_disabled_reason") or "").strip()

        loaded = None
        if load_id:
            loaded = db.query_one("SELECT * FROM comm_templates WHERE id = ?", (load_id,))
            loaded = dict(loaded) if loaded else None
            if loaded:
                loaded["attachments"] = fetch_template_attachments(db, int(loaded["id"]))

        templates = db.query("""
            SELECT
              ct.*,
              st.name AS subscription_template_name
            FROM comm_templates ct
            LEFT JOIN subscription_templates st ON st.id = ct.subscription_template_id
            ORDER BY ct.enabled DESC, LOWER(ct.name), ct.id DESC
        """)
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
            duplicate_disabled=duplicate_disabled,
            duplicate_disabled_reason=duplicate_disabled_reason,
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
        order = (request.args.get("order") or "desc").strip().lower()

        if order not in ("asc", "desc"):
            order = "desc"

        sent_at_sort_expr = """
            COALESCE(
                CASE
                    WHEN typeof(h.sent_at) = 'integer' THEN h.sent_at
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

        total_row = db.query_one("SELECT COUNT(*) AS total FROM comm_history")
        total_rows = int(total_row["total"]) if total_row and total_row["total"] is not None else 0
        total_pages = max((total_rows + per_page - 1) // per_page, 1)

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * per_page

        rows = db.query(
            f"""
            SELECT
                h.*,
                u.username AS user_username,
                t.key AS template_key,
                t.subject AS template_subject,
                t.body AS template_body,
                c.name AS campaign_name,
                c.subject AS campaign_subject,
                c.body AS campaign_body
            FROM comm_history h
            LEFT JOIN vodum_users u ON u.id = h.user_id
            LEFT JOIN comm_templates t ON t.id = h.template_id
            LEFT JOIN comm_campaigns c ON c.id = h.campaign_id
            ORDER BY {order_by_sql}
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )

        history = [dict(r) for r in (rows or [])]

        for h in history:
            try:
                h["meta"] = json.loads(h.get("meta_json") or "{}")
            except Exception:
                h["meta"] = {}

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
        )


    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @app.route("/communications/configuration/action", methods=["POST"])
    def communications_configuration_action():
        db = get_db()
        t = get_translator()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
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

            # Safety: do not wipe secrets on auto-save if input is empty
            smtp_pass_raw = request.form.get("smtp_pass")
            smtp_pass = (smtp_pass_raw or "")
            if smtp_pass_raw is not None and smtp_pass_raw.strip() == "":
                smtp_pass = settings.get("smtp_pass") or ""

            # Discord
            discord_enabled = 1 if request.form.get("discord_enabled") == "1" else 0
            discord_bot_token_raw = request.form.get("discord_bot_token")
            discord_bot_token = (discord_bot_token_raw or "").strip() or None
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
                  discord_enabled=?,
                  discord_bot_token=?,
                  notifications_send_mode=?,
                  notifications_order=?,
                  user_notifications_can_override=?
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
                    discord_enabled,
                    discord_bot_token,
                    send_mode,
                    notifications_order,
                    user_can_override,
                ),
            )

            add_log("info", "communications", "Communication settings updated")
            flash(t("comm_config_saved"), "success")
            return redirect(url_for("communications_configuration_page"))

        # Queue retry of failed scheduled communications
        if action == "retry_scheduled_errors":
            try:
                db.execute(
                    """
                    UPDATE comm_scheduled
                    SET status = 'pending',
                        last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'error'
                    """
                )
                try:
                    enable_and_run_task_by_name("send_expiration_emails")
                except Exception:
                    pass

                add_log("info", "communications", "Scheduled communication errors requeued")
                flash(t("comm_retry_scheduled_success"), "success")
            except Exception as e:
                flash(f"{t('comm_retry_scheduled_error')}: {e}", "error")

            return redirect(url_for("communications_configuration_page"))

        flash(t("comm_not_found"), "error")
        return redirect(url_for("communications_configuration_page"))


    @app.route("/communications/configuration", methods=["GET"])
    def communications_configuration_page():
        db = get_db()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        recent_scheduled = db.query(
            """
            SELECT *
            FROM comm_scheduled
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """
        ) or []
        recent_scheduled = [dict(r) for r in recent_scheduled]

        recent_history = db.query(
            """
            SELECT
                h.*,
                u.username AS user_username
            FROM comm_history h
            LEFT JOIN vodum_users u ON u.id = h.user_id
            ORDER BY h.id DESC
            LIMIT 50
            """
        ) or []
        recent_history = [dict(r) for r in recent_history]

        for row in recent_history:
            try:
                row["meta"] = json.loads(row.get("meta_json") or "{}")
            except Exception:
                row["meta"] = {}

        return render_template(
            "communications/communications_configuration.html",
            settings=settings,
            recent_scheduled=recent_scheduled,
            recent_history=recent_history,
            current_subpage="configuration",
        )
