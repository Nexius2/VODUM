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

def register(app):
    @app.route("/mailing/templates", methods=["GET", "POST"])
    def mailing_templates_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        t = get_translator()

        # ---------------------------------------------------
        # S’assurer que les 3 templates existent
        # ---------------------------------------------------
        for type_ in ("preavis", "relance", "fin"):
            exists = db.query_one(
                "SELECT 1 FROM email_templates WHERE type = ?",
                (type_,),
            )
            if not exists:
                db.execute(
                    """
                    INSERT INTO email_templates(type, subject, body, days_before)
                    VALUES (?, '', '', 0)
                    """,
                    (type_,),
                )

        # ---------------------------------------------------
        # SAUVEGARDE DES MODIFICATIONS
        # ---------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "save":

            # -----------------------------
            # Délais globaux (settings)
            # -----------------------------
            settings = db.query_one(
                "SELECT preavis_days, reminder_days FROM settings WHERE id = 1"
            )

            try:
                preavis_days = int(request.form.get("preavis_days"))
            except Exception:
                preavis_days = settings["preavis_days"]

            try:
                reminder_days = int(request.form.get("reminder_days"))
            except Exception:
                reminder_days = settings["reminder_days"]

            db.execute(
                """
                UPDATE settings
                SET preavis_days = ?, reminder_days = ?
                WHERE id = 1
                """,
                (preavis_days, reminder_days),
            )

            # -----------------------------
            # Mise à jour des templates
            # -----------------------------
            templates = db.query(
                "SELECT * FROM email_templates"
            )

            for tpl in templates:
                tid = tpl["id"]

                subject = request.form.get(f"subject_{tid}", "").strip()
                body = request.form.get(f"body_{tid}", "").strip()

                db.execute(
                    """
                    UPDATE email_templates
                    SET subject = ?, body = ?
                    WHERE id = ?
                    """,
                    (subject, body, tid),
                )

            add_log(
                "info",
                "mail_templates",
                "Templates updated",
                {
                    "preavis_days": preavis_days,
                    "reminder_days": reminder_days,
                },
            )

            flash(t("templates_saved"), "success")

        # ---------------------------------------------------
        # ENVOI DE TEST (INCHANGÉ)
        # ---------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "test":
            template_id = request.form.get("test_template_id", type=int)

            settings = db.query_one(
                "SELECT * FROM settings WHERE id = 1"
            )
            admin_email = settings["admin_email"] if settings else None

            if not admin_email:
                flash(t("admin_email_missing"), "error")
            else:
                tpl = db.query_one(
                    "SELECT * FROM email_templates WHERE id = ?",
                    (template_id,),
                )

                if not tpl:
                    flash(t("template_not_found"), "error")
                else:
                    try:
                        test_user = {
                            "username": "TestUser",
                            "email": admin_email,
                            "expiration_date": "2025-12-31",
                        }

                        context = build_user_context(test_user)

                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        send_email_via_settings(
                            admin_email,
                            subject,
                            body,
                        )

                        add_log(
                            "info",
                            "mail_templates",
                            f"Test email sent ({tpl['type']})",
                            {"template_id": tpl["id"]},
                        )
                        flash(t("template_test_sent"), "success")

                    except Exception as e:
                        add_log(
                            "error",
                            "mail_templates",
                            "Template test failed",
                            {"error": str(e)},
                        )
                        flash(
                            f"{t('template_test_failed')} ({e})",
                            "error",
                        )

        # ---------------------------------------------------
        # AFFICHAGE
        # ---------------------------------------------------
        templates = db.query(
            "SELECT * FROM email_templates ORDER BY type"
        )

        return render_template(
            "mailing/mailing_templates.html",
            templates=templates,
            active_page="mailing",
        )


    @app.route("/mailing/welcome-templates", methods=["GET", "POST"])
    def mailing_welcome_templates_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        t = get_translator()

        # Create/override empty row
        if request.method == "POST" and request.form.get("action") == "create_or_override":
            provider = (request.form.get("provider") or "").strip().lower()
            server_id_raw = (request.form.get("server_id") or "").strip()
            server_id = int(server_id_raw) if server_id_raw else None

            if provider not in ("plex", "jellyfin"):
                flash("Invalid provider", "error")
            else:
                exists = db.query_one(
                    """
                    SELECT 1 FROM welcome_email_templates
                    WHERE provider=? AND server_id IS ?
                    """,
                    (provider, server_id),
                )
                if not exists:
                    db.execute(
                        """
                        INSERT INTO welcome_email_templates(provider, server_id, subject, body)
                        VALUES (?, ?, ?, ?)
                        """,
                        (provider, server_id, "", ""),
                    )
                    flash("Template created.", "success")

        # Save all
        if request.method == "POST" and request.form.get("action") == "save_all":
            rows = db.query("SELECT id FROM welcome_email_templates")
            for r in rows:
                tid = r["id"]
                subject = request.form.get(f"subject_{tid}", "").strip()
                body = request.form.get(f"body_{tid}", "").strip()
                db.execute(
                    """
                    UPDATE welcome_email_templates
                    SET subject=?, body=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (subject, body, tid),
                )
            add_log("info", "mail_templates", "Welcome templates updated", {})
            flash("Welcome templates saved.", "success")

        # Test send
        if request.method == "POST" and request.form.get("test_template_id"):
            template_id = request.form.get("test_template_id", type=int)

            settings = db.query_one("SELECT * FROM settings WHERE id = 1")
            settings = dict(settings) if settings else {}
            admin_email = settings["admin_email"] if settings else None

            if not admin_email:
                flash(t("admin_email_missing"), "error")
            else:
                tpl = db.query_one(
                    "SELECT * FROM welcome_email_templates WHERE id = ?",
                    (template_id,),
                )
                if not tpl:
                    flash("Template not found", "error")
                else:
                    try:
                        fake_user = {
                            "username": "TestUser",
                            "email": admin_email,
                            "expiration_date": "2026-12-31",
                            "firstname": "John",
                            "lastname": "Doe",
                            "server_name": "My Server",
                            "server_url": "https://example.com",
                            "login_username": "TestUser",
                            "temporary_password": "TempPass123!",
                        }
                        context = build_user_context(fake_user)
                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        send_email_via_settings(admin_email, subject, body)

                        add_log("info", "mail_templates", "Welcome template test email sent", {"template_id": template_id})
                        flash("Test email sent to admin.", "success")
                    except Exception as e:
                        add_log("error", "mail_templates", "Welcome template test failed", {"error": str(e)})
                        flash(f"Test failed ({e})", "error")

        templates = db.query("""
            SELECT w.*,
                   s.name as server_name
            FROM welcome_email_templates w
            LEFT JOIN servers s ON s.id = w.server_id
            ORDER BY w.provider ASC, (w.server_id IS NOT NULL) ASC, s.name ASC
        """)

        servers = db.query("SELECT id, name, type FROM servers ORDER BY name ASC")

        return render_template(
            "mailing/mailing_welcome_templates.html",
            templates=templates,
            servers=servers,
            active_page="mailing",
            current_subpage="welcome_templates",
            settings=settings
        )


    # -------------------------------------------------------------------------
    # MAILING HISTORY (sent_emails + mail_campaigns)
    # -------------------------------------------------------------------------

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




