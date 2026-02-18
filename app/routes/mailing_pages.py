# Auto-split from app.py (keep URLs/endpoints intact)
import os
import json
import time
import re
import math
import platform
import ipaddress
import uuid
import threading
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from flask import (
    render_template, g, request, redirect, url_for, flash, session,
    Response, current_app, jsonify, make_response, abort,
)

from db_manager import DBManager
from logging_utils import get_logger, read_last_logs, read_all_logs
from tasks_engine import run_task, start_scheduler, run_task_sequence, run_task_by_name, enqueue_task
from mailing_utils import build_user_context, render_mail
from blueprints.users import is_smtp_ready
from discord_utils import is_discord_ready, validate_discord_bot_token
from core.i18n import get_translator, get_available_languages
from core.backup import BackupConfig, ensure_backup_dir, create_backup_file, list_backups, restore_backup_file
from werkzeug.security import generate_password_hash, check_password_hash

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg

task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

def _purge_email_history(db, retention_years):
    """Delete sent email history entries older than retention_years.
    retention_years <= 0 -> no purge.
    """
    try:
        ry = int(retention_years or 0)
    except Exception:
        ry = 0

    if ry <= 0:
        return {"sent_emails": 0, "mail_campaigns": 0}

    # SQLite: DATE('now', '-X years')
    threshold = f"-{ry} years"

    # sent_emails: use sent_at
    cur1 = db.execute(
        "DELETE FROM sent_emails WHERE sent_at < DATETIME('now', ?)",
        (threshold,),
    )

    # mail_campaigns: use created_at
    cur2 = db.execute(
        "DELETE FROM mail_campaigns WHERE created_at < DATETIME('now', ?)",
        (threshold,),
    )

    c1 = getattr(cur1, "rowcount", None) or 0
    c2 = getattr(cur2, "rowcount", None) or 0
    return {"sent_emails": c1, "mail_campaigns": c2}


def register(app):
    @app.route("/mailing")
    def mailing_page():
        db = get_db()

        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )
        settings = dict(settings) if settings else {}

        if is_smtp_ready(settings):
            return redirect(url_for("mailing_campaigns_page"))

        return redirect(url_for("mailing_smtp_page"))






    @app.route("/mailing/campaigns", methods=["GET", "POST"])
    def mailing_campaigns_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        t = get_translator()

        # Fetch list of servers for dropdown (READ)
        servers = db.query(
            "SELECT id, name FROM servers ORDER BY name"
        )

        # -----------------------------------------------------------------------------
        # 1. LOAD CAMPAIGN INTO FORM
        # -----------------------------------------------------------------------------
        load_id = request.args.get("load", type=int)
        loaded_campaign = None

        if load_id:
            loaded_campaign = db.query_one(
                "SELECT * FROM mail_campaigns WHERE id = ?",
                (load_id,),
            )

        # -----------------------------------------------------------------------------
        # 2. CREATE NEW CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "create":
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            server_id = request.form.get("server_id", type=int)
            
            # "All servers" ou valeur vide → NULL
            raw_server_id = request.form.get("server_id")
            server_id = None

            if raw_server_id:
                try:
                    sid = int(raw_server_id)
                    exists = db.query_one(
                        "SELECT 1 FROM servers WHERE id = ?",
                        (sid,),
                    )
                    if exists:
                        server_id = sid
                except ValueError:
                    server_id = None
            
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not subject or not body:
                flash(t("campaign_missing_fields"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            add_log(
                "debug",
                "mail_campaigns",
                "Normalized server_id",
                {"raw": raw_server_id, "final": server_id},
            )


            db.execute(
                """
                INSERT INTO mail_campaigns(
                    subject, body, server_id, status, is_test, created_at
                )
                VALUES (?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """,
                (subject, body, server_id, is_test),
            )

            add_log(
                "info",
                "mail_campaigns",
                "Campaign created",
                {"subject": subject, "is_test": is_test},
            )

            flash(t("campaign_created"), "success")
            return redirect(url_for("mailing_campaigns_page"))

        # -----------------------------------------------------------------------------
        # 2.b UPDATE EXISTING CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "save":
            cid = request.form.get("campaign_id", type=int)
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            server_id = request.form.get("server_id", type=int)
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not cid:
                flash(t("campaign_not_found"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            db.execute(
                """
                UPDATE mail_campaigns
                SET subject = ?, body = ?, server_id = ?, is_test = ?
                WHERE id = ?
                """,
                (subject, body, server_id, is_test, cid),
            )

            add_log(
                "info",
                "mail_campaigns",
                "Campaign updated",
                {"id": cid, "subject": subject},
            )

            flash(t("campaign_saved"), "success")
            return redirect(url_for("mailing_campaigns_page"))

        # -----------------------------------------------------------------------------
        # 3. SEND CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "send":
            cid = request.form.get("campaign_id", type=int)

            campaign = db.query_one(
                "SELECT * FROM mail_campaigns WHERE id = ?",
                (cid,),
            )
            if not campaign:
                flash(t("campaign_not_found"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            # Mark as sending
            db.execute(
                "UPDATE mail_campaigns SET status = 'sending' WHERE id = ?",
                (cid,),
            )

            settings = db.query_one("SELECT * FROM settings WHERE id = 1")
            settings = dict(settings) if settings else {}
            admin_email = settings["admin_email"] if settings else None

            # -----------------------------------------------------
            # TEST MODE
            # -----------------------------------------------------
            if campaign["is_test"]:
                try:
                    send_email_via_settings(
                        admin_email,
                        campaign["subject"],
                        campaign["body"],
                    )

                    db.execute(
                        """
                        UPDATE mail_campaigns
                        SET status = 'finished', finished_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (cid,),
                    )

                    flash(t("campaign_test_sent"), "success")

                except Exception as e:
                    db.execute(
                        """
                        UPDATE mail_campaigns
                        SET status = 'error', finished_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (cid,),
                    )

                    flash(f"{t('campaign_send_failed')} ({e})", "error")

                return redirect(url_for("mailing_campaigns_page"))

            # -----------------------------------------------------
            # REAL MASS SENDING
            # -----------------------------------------------------
            if campaign["server_id"]:
                # utilisateurs ayant AU MOINS un compte sur ce serveur
                users = db.query(
                    """
                    SELECT DISTINCT
                        vu.email,
                        vu.username,
                        vu.expiration_date
                    FROM vodum_users vu
                    JOIN media_users mu
                          ON mu.vodum_user_id = vu.id
                    WHERE mu.server_id = ?
                    """,
                    (campaign["server_id"],),
                )

            else:
                # toutes les personnes dans Vodum
                users = db.query(
                    """
                    SELECT
                        email,
                        username,
                        expiration_date
                    FROM vodum_users
                    """
                )

            errors = 0

            for u in users:
                if not u["email"]:
                    continue

                formatted_body = (
                    campaign["body"]
                    .replace("{username}", u["username"] or "")
                    .replace("{email}", u["email"] or "")
                    .replace("{expiration_date}", u["expiration_date"] or "")
                )

                try:
                    send_email_via_settings(
                        u["email"],
                        campaign["subject"],
                        formatted_body,
                    )
                except Exception as e:
                    errors += 1
                    add_log(
                        "error",
                        "mail_campaigns",
                        "Sending failed",
                        {
                            "user": u["email"],
                            "campaign": cid,
                            "error": str(e),
                        },
                    )

            final_status = "finished" if errors == 0 else "error"

            db.execute(
                """
                UPDATE mail_campaigns
                SET status = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (final_status, cid),
            )

            flash(t("campaign_sent"), "success")
            return redirect(url_for("mailing_campaigns_page"))


        # -----------------------------------------------------------------------------
        # 4. DISPLAY PAGE
        # -----------------------------------------------------------------------------
        campaigns = db.query(
            """
            SELECT c.*, s.name AS server_name
            FROM mail_campaigns c
            LEFT JOIN servers s ON s.id = c.server_id
            ORDER BY datetime(c.created_at) DESC
            """
        )

        return render_template(
            "mailing/mailing_campaigns.html",
            campaigns=campaigns,
            servers=servers,
            loaded_campaign=loaded_campaign,
            active_page="mailing",
        )





    @app.post("/mailing/campaigns/delete")
    def mailing_campaigns_delete():
        db = get_db()
        t = get_translator()

        ids = request.form.getlist("campaign_ids")

        if not ids:
            flash(t("no_campaign_selected"), "error")
            return redirect(url_for("mailing_campaigns_page"))

        placeholders = ",".join("?" for _ in ids)

        try:
            db.execute(
                f"DELETE FROM mail_campaigns WHERE id IN ({placeholders})",
                ids,
            )

            add_log(
                "info",
                "mail_campaigns",
                "Campaigns deleted",
                {"ids": ids},
            )

            flash(
                t("campaigns_deleted").format(count=len(ids)),
                "success",
            )

        except Exception as e:
            # Pas de rollback avec DBManager
            add_log(
                "error",
                "mail_campaigns",
                "Failed to delete campaigns",
                {"ids": ids, "error": str(e)},
            )

            flash(
                f"{t('campaign_delete_failed')} ({e})",
                "error",
            )

        return redirect(url_for("mailing_campaigns_page"))



    @app.route("/mailing/history")
    def mailing_history_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        # Retention purge (best-effort)
        try:
            _purge_email_history(db, (settings["email_history_retention_years"] if settings else 0))
        except Exception as e:
            add_log("error", "mailing_history", "Retention purge failed", {"error": str(e)})

        history = db.query(
            """
            SELECT
                'user' AS source,
                se.id AS id,
                se.user_id AS user_id,
                se.template_type AS type,
                NULL AS subject,
                vu.username AS username,
                vu.email AS email,
                NULL AS server_name,
                NULL AS status,
                se.expiration_date AS expiration_date,
                se.sent_at AS date
            FROM sent_emails se
            JOIN vodum_users vu ON vu.id = se.user_id

            UNION ALL

            SELECT
                'campaign' AS source,
                mc.id AS id,
                NULL AS user_id,
                'campaign' AS type,
                mc.subject AS subject,
                NULL AS username,
                NULL AS email,
                COALESCE(s.name, '-') AS server_name,
                mc.status AS status,
                NULL AS expiration_date,
                mc.created_at AS date
            FROM mail_campaigns mc
            LEFT JOIN servers s ON s.id = mc.server_id

            ORDER BY date DESC
            """
        )

        return render_template(
            "mailing/mailing_history.html",
            settings=settings,
            history=history,
        )


    @app.post("/mailing/history/retention")
    def mailing_history_retention():
        db = get_db()
        t = get_translator()

        years_raw = request.form.get("retention_years", "").strip()
        try:
            years = int(years_raw)
        except Exception:
            years = 2

        if years < 0:
            years = 0
        if years > 50:
            years = 50

        db.execute(
            "UPDATE settings SET email_history_retention_years = ? WHERE id = 1",
            (years,),
        )

        add_log("info", "mailing_history", "Retention updated", {"years": years})
        flash(t("retention_saved").format(years=years), "success")
        return redirect(url_for("mailing_history_page"))


    @app.post("/mailing/history/purge")
    def mailing_history_purge():
        db = get_db()
        t = get_translator()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        years = (settings["email_history_retention_years"] if settings else 0)

        try:
            counts = _purge_email_history(db, years)
            flash(
                t("history_purged").format(sent=counts["sent_emails"], campaigns=counts["mail_campaigns"]),
                "success",
            )
            add_log("info", "mailing_history", "History purged", {"years": years, **counts})
        except Exception as e:
            add_log("error", "mailing_history", "Purge failed", {"error": str(e)})
            flash(f"{t('purge_failed')} ({e})", "error")

        return redirect(url_for("mailing_history_page"))


    @app.post("/mailing/history/delete")
    def mailing_history_delete():
        db = get_db()
        t = get_translator()

        items = request.form.getlist("items")
        if not items:
            flash(t("no_item_selected"), "error")
            return redirect(url_for("mailing_history_page"))

        sent_ids = []
        camp_ids = []
        for it in items:
            try:
                src, rid = it.split(":", 1)
                rid = int(rid)
            except Exception:
                continue
            if src == "user":
                sent_ids.append(rid)
            elif src == "campaign":
                camp_ids.append(rid)

        try:
            total = 0
            if sent_ids:
                placeholders = ",".join("?" for _ in sent_ids)
                db.execute(f"DELETE FROM sent_emails WHERE id IN ({placeholders})", sent_ids)
                total += len(sent_ids)

            if camp_ids:
                placeholders = ",".join("?" for _ in camp_ids)
                db.execute(f"DELETE FROM mail_campaigns WHERE id IN ({placeholders})", camp_ids)
                total += len(camp_ids)

            add_log("info", "mailing_history", "History rows deleted", {"sent_ids": sent_ids, "campaign_ids": camp_ids})
            flash(t("items_deleted").format(count=total), "success")

        except Exception as e:
            add_log("error", "mailing_history", "Delete failed", {"error": str(e)})
            flash(f"{t('delete_failed')} ({e})", "error")

        return redirect(url_for("mailing_history_page"))



    @app.route("/mailing/smtp", methods=["GET", "POST"])
    def mailing_smtp_page():
        db = get_db()
        t = get_translator()

        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )

        if request.method == "POST":
            action = request.form.get("action")

            # --------------------------------------------------
            # SAVE SMTP SETTINGS
            # --------------------------------------------------
            if action == "save":
                mail_from = request.form.get("mail_from") or None
                smtp_host = request.form.get("smtp_host") or None
                smtp_port = request.form.get("smtp_port", type=int)
                smtp_tls = 1 if request.form.get("smtp_tls") == "1" else 0
                smtp_user = request.form.get("smtp_user") or None
                smtp_pass = request.form.get("smtp_pass") or None

                db.execute(
                    """
                    UPDATE settings
                    SET mail_from = ?, smtp_host = ?, smtp_port = ?, smtp_tls = ?,
                        smtp_user = ?, smtp_pass = ?
                    WHERE id = 1
                    """,
                    (mail_from, smtp_host, smtp_port, smtp_tls, smtp_user, smtp_pass),
                )

                add_log(
                    "info",
                    "smtp_config",
                    "SMTP settings updated",
                    None,
                )
                flash(t("smtp_settings_saved"), "success")

            # --------------------------------------------------
            # TEST SMTP
            # --------------------------------------------------
            elif action == "test":
                admin_email = settings["admin_email"] if settings else None

                if not admin_email:
                    flash(t("admin_email_missing"), "error")
                else:
                    try:
                        send_email_via_settings(
                            admin_email,
                            t("smtp_test_subject"),
                            t("smtp_test_body"),
                        )

                        add_log(
                            "info",
                            "smtp_config",
                            "SMTP test email sent",
                            {"to": admin_email},
                        )
                        flash(t("smtp_test_sent"), "success")

                    except Exception as e:
                        add_log(
                            "error",
                            "smtp_config",
                            "SMTP test failed",
                            {"error": str(e)},
                        )
                        flash(
                            f"{t('smtp_test_failed')} ({e})",
                            "error",
                        )

            return redirect(url_for("mailing_smtp_page"))

        return render_template(
            "mailing/mailing_smtp.html",
            settings=settings,
            active_page="mailing",
        )

    # -----------------------------
    # DISCORD
    # -----------------------------

    def is_discord_ready(settings) -> bool:
        if not settings:
            return False
        try:
            return bool(
                settings.get("discord_enabled")
                and (settings.get("discord_bot_token") or "").strip()
            )
        except Exception:
            return False


    @app.post("/api/discord/toggle")
    def api_discord_toggle():
        db = get_db()
        data = request.get_json(silent=True) or {}
        enabled = 1 if data.get("enabled") else 0

        try:
            # read current token
            settings = db.query_one("SELECT discord_bot_token FROM settings WHERE id = 1")
            token = (dict(settings).get("discord_bot_token") or "").strip() if settings else ""

            # If enabling, validate token NOW (real check against Discord)
            if enabled == 1:
                ok, detail = validate_discord_bot_token(token)
                if not ok:
                    # force disabled in DB to avoid "enabled but broken"
                    db.execute("UPDATE settings SET discord_enabled = ? WHERE id = 1", (0,))
                    db.execute(
                        """
                        UPDATE tasks
                        SET enabled = ?,
                            status  = 'disabled'
                        WHERE name IN ('send_expiration_discord', 'send_campaign_discord')
                        """,
                        (0,),
                    )
                    return {"status": "error", "message": f"Discord token invalid: {detail}"}, 400

            # 1) update settings flag
            db.execute(
                "UPDATE settings SET discord_enabled = ? WHERE id = 1",
                (enabled,),
            )

            # 2) enable/disable discord tasks
            db.execute(
                """
                UPDATE tasks
                SET enabled = ?,
                    status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END
                WHERE name IN ('send_expiration_discord', 'send_campaign_discord')
                """,
                (enabled, enabled),
            )

            add_log("info", "discord", f"Discord toggled → {enabled}")
            return {"status": "ok", "enabled": enabled}

        except Exception as e:
            add_log("error", "discord", "Failed to toggle discord", {"error": str(e)})
            return {"status": "error", "message": str(e)}, 500

    @app.get("/api/discord/token")
    def api_discord_token():
        db = get_db()
        try:
            row = db.query_one("SELECT discord_bot_token FROM settings WHERE id = 1")
            token = (dict(row).get("discord_bot_token") or "").strip() if row else ""

            if not token:
                return {"status": "error", "message": "No discord token configured"}, 404

            # NOTE: This returns the raw token on purpose (admin UI feature).
            return {"status": "ok", "token": token}
        except Exception as e:
            add_log("error", "discord", "Failed to read discord token", {"error": str(e)})
            return {"status": "error", "message": str(e)}, 500



