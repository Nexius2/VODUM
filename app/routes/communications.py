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
    send_to_user,
    record_history,
    attempts_satisfy_mode,
    available_channels,
)
from tasks_engine import enqueue_task


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


def _enqueue_send_comm_campaigns(db) -> bool:
    row = db.query_one(
        """
        SELECT id, enabled
        FROM tasks
        WHERE name = 'send_comm_campaigns'
        LIMIT 1
        """
    )
    if not row:
        return False

    if not int(row["enabled"] or 0):
        return False

    try:
        before = db.query_one(
            "SELECT queued_count FROM tasks WHERE id = ?",
            (int(row["id"]),),
        )
        before_q = int(before["queued_count"] or 0) if before else 0

        enqueue_task(int(row["id"]))

        after = db.query_one(
            "SELECT queued_count FROM tasks WHERE id = ?",
            (int(row["id"]),),
        )
        after_q = int(after["queued_count"] or 0) if after else 0

        return after_q > before_q
    except Exception:
        return False


def _normalize_send_mode(settings: dict) -> str:
    mode = (settings or {}).get("notifications_send_mode")
    mode = (mode or "first").strip().lower()
    return mode if mode in ("first", "all") else "first"


def _campaign_attempts_satisfy_mode(db, settings: dict, user: dict, attempts: list) -> bool:
    """
    Campaign success rule:
    - FIRST: at least one successful channel
    - ALL  : all available channels for this user must succeed
    """
    mode = _normalize_send_mode(settings)
    avail = available_channels(db, settings, user)

    sent_channels = {a.channel for a in (attempts or []) if getattr(a, "status", None) == "sent"}

    if mode == "all":
        required = []
        if avail.get("email"):
            required.append("email")
        if avail.get("discord"):
            required.append("discord")

        # No usable channel => failure
        if not required:
            return False

        return all(ch in sent_channels for ch in required)

    return any(getattr(a, "status", None) == "sent" for a in (attempts or []))

def register(app):

    @app.route("/communications")
    def communications_page():
        return redirect(url_for("communications_campaigns_page"))


    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    @app.route("/communications/campaigns", methods=["GET", "POST"])
    def communications_campaigns_page():
        db = get_db()
        t = get_translator()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        servers = db.query("SELECT id, name FROM servers ORDER BY name")

        load_id = request.args.get("load", type=int)
        loaded = None
        if load_id:
            loaded = db.query_one("SELECT * FROM comm_campaigns WHERE id = ?", (load_id,))
            loaded = dict(loaded) if loaded else None
            if loaded:
                loaded["attachments"] = fetch_campaign_attachments(db, int(loaded["id"]))

        # Create
        if request.method == "POST" and request.form.get("action") == "create":
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
                VALUES(?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (name, subject, body, server_id, is_test),
            )
            cid = getattr(cur, 'lastrowid', None)

            # attachments
            files = request.files.getlist("attachments")
            saved = store_uploads("campaign", int(cid), files)
            for att in saved:
                db.execute(
                    "INSERT INTO comm_campaign_attachments(campaign_id, filename, mime_type, path) VALUES(?,?,?,?)",
                    (cid, att["filename"], att.get("mime_type"), att["path"]),
                )

            add_log("info", "communications", "Campaign created", {"id": cid, "name": name})
            flash(t("comm_campaign_created"), "success")
            return redirect(url_for("communications_campaigns_page"))

        # Save
        if request.method == "POST" and request.form.get("action") == "save":
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
        if request.method == "POST" and request.form.get("action") == "delete":
            cid = request.form.get("campaign_id", type=int)
            if not cid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))
            db.execute("DELETE FROM comm_campaigns WHERE id = ?", (cid,))
            add_log("info", "communications", "Campaign deleted", {"id": cid})
            flash(t("comm_campaign_deleted"), "success")
            return redirect(url_for("communications_campaigns_page"))

        # Send
        if request.method == "POST" and request.form.get("action") == "send":
            cid = request.form.get("campaign_id", type=int)
            campaign = db.query_one("SELECT * FROM comm_campaigns WHERE id = ?", (cid,))
            if not campaign:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_campaigns_page"))
            campaign = dict(campaign)

            attachments = fetch_campaign_attachments(db, cid)

            # Users target: only users linked to at least one media user (same logic as reminders)
            users = db.query(
                """
                SELECT id, username, email, second_email, discord_user_id, notifications_order_override
                FROM vodum_users u
                WHERE EXISTS (SELECT 1 FROM media_users mu WHERE mu.vodum_user_id = u.id)
                """
            )

            # If campaign has a server_id, restrict to users with at least one media_user on that server
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

            # TEST mode stays immediate
            if int(campaign.get("is_test") or 0) == 1:
                admin_email = (settings.get("admin_email") or "").strip()
                if not admin_email:
                    db.execute("UPDATE comm_campaigns SET status='error', updated_at=CURRENT_TIMESTAMP WHERE id=?", (cid,))
                    flash(t("comm_admin_email_missing"), "error")
                    return redirect(url_for("communications_campaigns_page", load=cid))

                fake_user = {
                    "id": None,
                    "username": "admin",
                    "email": admin_email,
                    "second_email": None,
                    "discord_user_id": None,
                    "notifications_order_override": None,
                }

                attempts = send_to_user(
                    db=db,
                    settings=settings,
                    user=fake_user,
                    subject=campaign.get("subject") or "",
                    body=campaign.get("body") or "",
                    attachments=attachments,
                )
                for att in attempts:
                    record_history(
                        db=db,
                        kind="campaign",
                        template_id=None,
                        campaign_id=cid,
                        user_id=None,
                        attempt=att,
                        meta={"is_test": True, "campaign_id": cid, "campaign_name": campaign.get("name")},
                    )

                test_ok = _campaign_attempts_satisfy_mode(db, settings, fake_user, attempts)
                db.execute(
                    "UPDATE comm_campaigns SET status=?, sent_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    ("finished" if test_ok else "error", cid),
                )
                flash(
                    t("comm_campaign_test_sent") if test_ok else t("comm_campaign_send_failed"),
                    "success" if test_ok else "error"
                )
                return redirect(url_for("communications_campaigns_page", load=cid))

            target_users = [dict(u) for u in (users or [])]
            if not target_users:
                db.execute(
                    "UPDATE comm_campaigns SET status='error', sent_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (cid,),
                )
                flash(t("comm_campaign_send_failed"), "error")
                return redirect(url_for("communications_campaigns_page", load=cid))

            # If campaign is not already sending, rebuild queue from scratch
            if (campaign.get("status") or "").strip().lower() != "sending":
                db.execute("DELETE FROM comm_campaign_targets WHERE campaign_id = ?", (cid,))

            queued = 0
            for u in target_users:
                user_id = int(u["id"])
                dedupe_key = f"campaign:{cid}:user:{user_id}"
                cur = db.execute(
                    """
                    INSERT OR IGNORE INTO comm_campaign_targets(
                        campaign_id, user_id, status,
                        attempt_count, max_attempts, next_attempt_at, last_attempt_at,
                        last_error, channels_sent, dedupe_key,
                        created_at, updated_at
                    )
                    VALUES(
                        ?, ?, 'pending',
                        0, 10, NULL, NULL,
                        NULL, NULL, ?,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (cid, user_id, dedupe_key),
                )
                if getattr(cur, "rowcount", 0):
                    queued += 1

            db.execute(
                "UPDATE comm_campaigns SET status='sending', sent_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (cid,),
            )

            task_enqueued = _enqueue_send_comm_campaigns(db)

            add_log(
                "info",
                "communications",
                "Campaign queued",
                {
                    "campaign_id": cid,
                    "queued_targets": queued,
                    "task_enqueued": task_enqueued,
                    "attachments": [a.get("filename") for a in (attachments or [])],
                },
            )

            if not task_enqueued:
                db.execute(
                    "UPDATE comm_campaigns SET status='error', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (cid,),
                )
                flash(t("comm_campaign_send_failed"), "error")
                return redirect(url_for("communications_campaigns_page", load=cid))

            flash(t("comm_campaign_queued_summary").format(ok=len(target_users), failed=0), "success")
            return redirect(url_for("communications_campaigns_page", load=cid))

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
    @app.route("/communications/templates", methods=["GET", "POST"])
    def communications_templates_page():
        db = get_db()
        t = get_translator()

        load_id = request.args.get("load", type=int)
        loaded = None
        if load_id:
            loaded = db.query_one("SELECT * FROM comm_templates WHERE id = ?", (load_id,))
            loaded = dict(loaded) if loaded else None
            if loaded:
                loaded["attachments"] = fetch_template_attachments(db, int(loaded["id"]))

        if request.method == "POST" and request.form.get("action") == "create":
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            enabled = 1 if request.form.get("enabled") == "1" else 0

            # Key is optional (UI hides it). We generate a stable one from the name.
            key = _sanitize_key(request.form.get("key") or "")
            if not key:
                base = _sanitize_key(name) or "template"
                key = base
                n = 2
                while db.query_one("SELECT 1 FROM comm_templates WHERE key = ?", (key,)):
                    key = f"{base}_{n}"
                    n += 1

            trigger_event = (request.form.get("trigger_event") or "expiration").strip().lower()
            if trigger_event not in ("expiration", "user_creation", "referral_reward", "expiration_change"):
                trigger_event = "expiration"

            trigger_provider = (request.form.get("trigger_provider") or "all").strip().lower()
            if trigger_provider not in ("all", "plex", "jellyfin"):
                trigger_provider = "all"

            expiration_change_direction = (request.form.get("expiration_change_direction") or "all").strip().lower()
            if expiration_change_direction not in ("all", "increase", "decrease"):
                expiration_change_direction = "all"

            if trigger_event != "expiration_change":
                expiration_change_direction = "all"

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

            # -----------------------------
            # Delay rules
            # - user_creation  => ONLY days_after (cannot be "before")
            # - expiration     => [X] days (before/after) the event
            # -----------------------------
            delay_direction = (request.form.get("delay_direction") or "").strip().lower()
            if delay_direction not in ("before", "after"):
                delay_direction = "before"

            # Normalize negatives
            if isinstance(days_before, int) and days_before < 0:
                days_before = 0
            if isinstance(days_after, int) and days_after < 0:
                days_after = 0

            if trigger_event == "user_creation":
                days_before = None
                if days_after is None:
                    days_after = 0
                delay_direction = "after"
            elif trigger_event in ("referral_reward", "expiration_change"):
                days_before = None
                days_after = 0
                delay_direction = "after"
            else:
                # expiration: keep ONLY one value (before OR after)
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
            tid = getattr(cur, 'lastrowid', None)

            files = request.files.getlist("attachments")
            saved = store_uploads("template", int(tid), files)
            for att in saved:
                db.execute(
                    "INSERT INTO comm_template_attachments(template_id, filename, mime_type, path) VALUES(?,?,?,?)",
                    (tid, att["filename"], att.get("mime_type"), att["path"]),
                )

            add_log("info", "communications", "Template created", {"id": tid, "key": key})
            flash(t("comm_template_created"), "success")
            return redirect(url_for("communications_templates_page", load=tid))

        if request.method == "POST" and request.form.get("action") == "save":
            tid = request.form.get("template_id", type=int)
            name = (request.form.get("name") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            enabled = 1 if request.form.get("enabled") == "1" else 0

            trigger_event = (request.form.get("trigger_event") or "expiration").strip().lower()
            if trigger_event not in ("expiration", "user_creation", "referral_reward", "expiration_change"):
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
                        "SELECT id FROM subscription_templates WHERE id = ?",
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
                        "SELECT id FROM subscription_templates WHERE id = ?",
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

            # -----------------------------
            # Delay rules
            # - user_creation  => ONLY days_after (cannot be "before")
            # - expiration     => [X] days (before/after) the event
            # -----------------------------
            delay_direction = (request.form.get("delay_direction") or "").strip().lower()
            if delay_direction not in ("before", "after"):
                delay_direction = "before"

            # Normalize negatives
            if isinstance(days_before, int) and days_before < 0:
                days_before = 0
            if isinstance(days_after, int) and days_after < 0:
                days_after = 0

            if trigger_event == "user_creation":
                days_before = None
                if days_after is None:
                    days_after = 0
                delay_direction = "after"
            elif trigger_event in ("referral_reward", "expiration_change"):
                days_before = None
                days_after = 0
                delay_direction = "after"
            else:
                # expiration: keep ONLY one value (before OR after)
                if delay_direction == "after":
                    offset = days_after if days_after is not None else (days_before if days_before is not None else 0)
                    days_after = offset
                    days_before = None
                else:
                    offset = days_before if days_before is not None else (days_after if days_after is not None else 0)
                    days_before = offset
                    days_after = None

            if not tid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))

            db.execute(
                """
                UPDATE comm_templates
                SET
                  name=?,
                  enabled=?,
                  trigger_event=?,
                  trigger_provider=?,
                  expiration_change_direction=?,
                  subscription_scope=?,
                  subscription_template_id=?,
                  days_before=?,
                  days_after=?,
                  subject=?,
                  body=?,
                  updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    name, enabled, trigger_event, trigger_provider,
                    expiration_change_direction,
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

            add_log("info", "communications", "Template updated", {"id": tid})
            flash(t("comm_template_saved"), "success")
            return redirect(url_for("communications_templates_page", load=tid))

        if request.method == "POST" and request.form.get("action") == "delete":
            tid = request.form.get("template_id", type=int)
            if not tid:
                flash(t("comm_not_found"), "error")
                return redirect(url_for("communications_templates_page"))
            db.execute("DELETE FROM comm_templates WHERE id = ?", (tid,))
            add_log("info", "communications", "Template deleted", {"id": tid})
            flash(t("comm_template_deleted"), "success")
            return redirect(url_for("communications_templates_page"))

        templates = db.query("""
            SELECT
              ct.*,
              st.name AS subscription_template_name
            FROM comm_templates ct
            LEFT JOIN subscription_templates st ON st.id = ct.subscription_template_id
            ORDER BY ct.key
        """)
        templates = [dict(r) for r in (templates or [])]

        subscription_templates = db.query(
            "SELECT id, name FROM subscription_templates ORDER BY name"
        ) or []
        subscription_templates = [dict(r) for r in subscription_templates]

        return render_template(
            "communications/communications_templates.html",
            templates=templates,
            loaded_template=loaded,
            subscription_templates=subscription_templates,
            current_subpage="templates",
        )


    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    @app.route("/communications/history")
    def communications_history_page():
        db = get_db()

        rows = db.query(
            """
            SELECT h.*, u.username AS user_username,
                   t.key AS template_key,
                   c.name AS campaign_name
            FROM comm_history h
            LEFT JOIN vodum_users u ON u.id = h.user_id
            LEFT JOIN comm_templates t ON t.id = h.template_id
            LEFT JOIN comm_campaigns c ON c.id = h.campaign_id
            ORDER BY
              COALESCE(
                CASE
                  WHEN typeof(h.sent_at) = 'integer' THEN h.sent_at
                  WHEN typeof(h.sent_at) = 'text' AND h.sent_at GLOB '[0-9]*' THEN CAST(h.sent_at AS INTEGER)
                  ELSE CAST(strftime('%s', h.sent_at) AS INTEGER)
                END,
                0
              ) DESC,
              h.id DESC
            LIMIT 500
            """
        )
        history = [dict(r) for r in (rows or [])]

        # best effort parse meta_json for UI
        for h in history:
            try:
                h["meta"] = json.loads(h.get("meta_json") or "{}")
            except Exception:
                h["meta"] = {}

        return render_template(
            "communications/communications_history.html",
            history=history,
            current_subpage="history",
        )


    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @app.route("/communications/configuration", methods=["GET", "POST"])
    def communications_configuration_page():
        db = get_db()
        t = get_translator()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        if request.method == "POST":
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

                # If it's an auto-save (fetch/HTMX), respond without redirect.
                if request.headers.get("HX-Request") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"ok": True})

                flash(t("comm_config_saved"), "success")
                return redirect(url_for("communications_configuration_page"))

            if action == "save_email":
                new_values = {
                    "mailing_enabled": 1 if request.form.get("mailing_enabled") == "1" else 0,
                    "mail_from": (request.form.get("mail_from") or "").strip() or None,
                    "smtp_host": (request.form.get("smtp_host") or "").strip() or None,
                    "smtp_port": _as_int(request.form.get("smtp_port"), None),
                    "smtp_tls": 1 if request.form.get("smtp_tls") == "1" else 0,
                    "smtp_user": (request.form.get("smtp_user") or "").strip() or None,
                    "smtp_pass": (request.form.get("smtp_pass") or ""),
                }

                db.execute(
                    """
                    UPDATE settings SET
                      mailing_enabled=:mailing_enabled,
                      mail_from=:mail_from,
                      smtp_host=:smtp_host,
                      smtp_port=:smtp_port,
                      smtp_tls=:smtp_tls,
                      smtp_user=:smtp_user,
                      smtp_pass=:smtp_pass
                    WHERE id=1
                    """,
                    new_values,
                )
                flash(t("comm_config_saved"), "success")
                return redirect(url_for("communications_configuration_page"))

            if action == "test_email":
                admin_email = (settings.get("admin_email") or "").strip()
                if not admin_email:
                    flash(t("comm_admin_email_missing"), "error")
                    return redirect(url_for("communications_configuration_page"))
                try:
                    send_email_via_settings(admin_email, t("comm_test_email_subject"), t("comm_test_email_body"))
                    flash(t("comm_test_ok"), "success")
                except Exception as e:
                    flash(t("comm_test_failed").format(error=str(e)), "error")
                return redirect(url_for("communications_configuration_page"))

            if action == "save_discord":
                discord_enabled = 1 if request.form.get("discord_enabled") == "1" else 0
                token = (request.form.get("discord_bot_token") or "").strip() or None

                db.execute(
                    "UPDATE settings SET discord_enabled=?, discord_bot_token=? WHERE id=1",
                    (discord_enabled, token),
                )
                flash(t("comm_config_saved"), "success")
                return redirect(url_for("communications_configuration_page"))

            if action == "test_discord":
                token = (request.form.get("discord_bot_token") or settings.get("discord_bot_token") or "").strip()
                ok, detail = validate_discord_bot_token(token)
                if ok:
                    flash(t("comm_discord_token_ok").format(bot=detail), "success")
                else:
                    flash(t("comm_discord_token_bad").format(error=detail), "error")
                return redirect(url_for("communications_configuration_page"))

            if action == "save_general":
                send_mode = (request.form.get("notifications_send_mode") or settings.get("notifications_send_mode") or "first").strip().lower()
                if send_mode not in ("first", "all"):
                    send_mode = "first"

                notifications_order = _sanitize_notifications_order(request.form.get("notifications_order") or settings.get("notifications_order") or "email")
                can_override = 1 if request.form.get("user_notifications_can_override") == "1" else 0

                db.execute(
                    "UPDATE settings SET notifications_send_mode=?, notifications_order=?, user_notifications_can_override=? WHERE id=1",
                    (send_mode, notifications_order, can_override),
                )

                flash(t("comm_config_saved"), "success")
                return redirect(url_for("communications_configuration_page"))

        # reload
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        return render_template(
            "communications/communications_configuration.html",
            settings=settings,
            current_subpage="configuration",
        )
