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
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        db = get_db()

        # ------------------------------
        # Charger settings (source unique)
        # ------------------------------
        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        settings = dict(settings)

        def _sanitize_notifications_order(raw: str) -> str:
            allowed = {"email", "discord"}
            raw = (raw or "").strip().lower()
            if not raw:
                return "email"

            parts = [p.strip() for p in raw.split(",") if p.strip()]
            cleaned = []
            for p in parts:
                if p in allowed and p not in cleaned:
                    cleaned.append(p)

            if not cleaned:
                return "email"
            if len(cleaned) == 1:
                return cleaned[0]
            return f"{cleaned[0]},{cleaned[1]}"


        # ------------------------------------------------------------
        # POST → SAVE ALL SETTINGS
        # ------------------------------------------------------------
        if request.method == "POST":

            # --------------------------------------------------
            # Expiration handling (2 exclusive modes)
            # --------------------------------------------------
            expiry_mode = (request.form.get("expiry_mode") or settings.get("expiry_mode") or "none").strip()
            if expiry_mode not in ("none", "disable", "warn_then_disable"):
                expiry_mode = "none"

            warn_then_disable_days_raw = (request.form.get("warn_then_disable_days") or settings.get("warn_then_disable_days") or 7)
            try:
                warn_then_disable_days = int(warn_then_disable_days_raw)
            except Exception:
                warn_then_disable_days = int(settings.get("warn_then_disable_days") or 7)

            # X days must be >= 1 (only meaningful for warn_then_disable)
            if warn_then_disable_days < 1:
                warn_then_disable_days = 1
                
            if expiry_mode != "warn_then_disable":
                warn_then_disable_days = int(settings.get("warn_then_disable_days") or 7)

            old_enable_cron_jobs = 1 if int(settings.get("enable_cron_jobs") or 0) == 1 else 0

            new_values = {
                "default_language": request.form.get(
                    "default_language", settings["default_language"]
                ),
                "timezone": request.form.get(
                    "timezone", settings["timezone"]
                ),
                "admin_email": request.form.get(
                    "admin_email", settings["admin_email"]
                ),
                "default_subscription_days": request.form.get(
                    "default_expiration_days",
                    settings["default_subscription_days"],
                ),
                "delete_after_expiry_days": request.form.get(
                    "delete_after_expiry_days",
                    settings["delete_after_expiry_days"],
                ),

                # ✅ délais statut (settings ONLY)
                "preavis_days": request.form.get(
                    "preavis_days",
                    settings["preavis_days"],
                ),
                "reminder_days": request.form.get(
                    "relance_days",
                    settings["reminder_days"],
                ),
                "brand_name": request.form.get("brand_name", settings.get("brand_name")),

                "notifications_order": _sanitize_notifications_order(
                    request.form.get("notifications_order", settings.get("notifications_order") or "email")
                ),
                "user_notifications_can_override": 1 if request.form.get("user_notifications_can_override") == "1" else 0,


                "expiry_mode": expiry_mode,
                "warn_then_disable_days": warn_then_disable_days,
                # legacy flag kept for backward compatibility
                "disable_on_expiry": 1 if expiry_mode == "disable" else 0,
                "enable_cron_jobs": 1 if request.form.get("enable_cron_jobs") == "1" else 0,
                "maintenance_mode": 1 if request.form.get("maintenance_mode") == "1" else 0,
                "debug_mode": 1 if request.form.get("debug_mode") == "1" else 0,
            }

            # --------------------------------------------------
            # Conversions INT (uniformes)
            # --------------------------------------------------
            for key in (
                "default_subscription_days",
                "delete_after_expiry_days",
                "preavis_days",
                "reminder_days",
                "warn_then_disable_days",
            ):
                try:
                    new_values[key] = int(new_values[key])
                except Exception:
                    new_values[key] = settings[key]

            # --------------------------------------------------
            # UPDATE settings (source unique)
            # --------------------------------------------------
            db.execute(
                """
                UPDATE settings SET
                    default_language = :default_language,
                    timezone = :timezone,
                    admin_email = :admin_email,
                    brand_name = :brand_name,
                    notifications_order = :notifications_order,
                    user_notifications_can_override = :user_notifications_can_override,
                    default_subscription_days = :default_subscription_days,
                    delete_after_expiry_days = :delete_after_expiry_days,
                    expiry_mode = :expiry_mode,
                    warn_then_disable_days = :warn_then_disable_days,
                    preavis_days = :preavis_days,
                    reminder_days = :reminder_days,
                    disable_on_expiry = :disable_on_expiry,
                    enable_cron_jobs = :enable_cron_jobs,
                    maintenance_mode = :maintenance_mode,
                    debug_mode = :debug_mode
                WHERE id = 1
                """,
                new_values,
            )

            # --------------------------------------------------
            # MASTER scheduled tasks switch (enable_cron_jobs)
            # - OFF  : disable ALL tasks and remember each task's previous enabled state
            # - ON   : restore each task to its remembered enabled state
            # --------------------------------------------------
            if old_enable_cron_jobs != new_values["enable_cron_jobs"]:
                if new_values["enable_cron_jobs"] == 0:
                    # Save previous enabled state (only once) then disable everything
                    db.execute(
                        '''
                        UPDATE tasks
                        SET
                            enabled_prev = CASE
                                WHEN enabled_prev IS NULL THEN enabled
                                ELSE enabled_prev
                            END,
                            enabled = 0,
                            status = 'disabled',
                            updated_at = CURRENT_TIMESTAMP
                        '''
                    )
                else:
                    # Restore previous state (and clear memory)
                    db.execute(
                        '''
                        UPDATE tasks
                        SET
                            enabled = CASE
                                WHEN enabled_prev IS NULL THEN enabled
                                ELSE enabled_prev
                            END,
                            status = CASE
                                WHEN (CASE WHEN enabled_prev IS NULL THEN enabled ELSE enabled_prev END) = 1 THEN 'idle'
                                ELSE 'disabled'
                            END,
                            enabled_prev = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        '''
                    )


            # --------------------------------------------------
            # Purge immédiate des policies système si on n'est plus en warn_then_disable
            # (évite d'attendre la prochaine exécution d'une tâche)
            # --------------------------------------------------
            if expiry_mode != "warn_then_disable":
                try:
                    rows = db.query("SELECT id, rule_value_json FROM stream_policies WHERE scope_type='user'") or []
                    purged = 0
                    for r in rows:
                        try:
                            rule = json.loads(r["rule_value_json"] or "{}")
                        except Exception:
                            rule = {}
                        if rule.get("system_tag") == "expired_subscription":
                            db.execute("DELETE FROM stream_policies WHERE id = ?", (int(r["id"]),))
                            purged += 1

                    if purged:
                        settings_logger.info(f"Purged {purged} expired_subscription system policy(ies) after settings change")
                except Exception:
                    settings_logger.error("Failed to purge expired_subscription policies after settings change", exc_info=True)


            # --------------------------------------------------
            # Update admin password (optional)
            # --------------------------------------------------
            new_pwd = request.form.get("admin_password") or ""
            new_pwd = new_pwd.strip()
            if new_pwd:
                if len(new_pwd) < 8:
                    flash("Mot de passe admin trop court (8 caractères minimum).", "error")
                    return redirect(url_for("settings_page"))

                db.execute(
                    "UPDATE settings SET admin_password_hash = ? WHERE id = 1",
                    (generate_password_hash(new_pwd),),
                )
                flash("Mot de passe admin mis à jour.", "success")


            # --------------------------------------------------
            # Sync TASKS from SETTINGS (source unique)
            # - If cron is enabled => update tasks.enabled directly
            # - If cron is disabled => keep tasks disabled, but store the desired state into tasks.enabled_prev
            # --------------------------------------------------
            disable_task_enabled = 1 if (
                new_values.get("expiry_mode") == "disable"
            ) else 0

            warn_task_enabled = 1 if (
                new_values.get("expiry_mode") == "warn_then_disable"
            ) else 0

            if new_values["enable_cron_jobs"] == 1:
                # Mode A
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = ?,
                        status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END
                    WHERE name = 'disable_expired_users'
                    """,
                    (disable_task_enabled, disable_task_enabled),
                )

                # Mode B
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = ?,
                        status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END
                    WHERE name = 'expired_subscription_manager'
                    """,
                    (warn_task_enabled, warn_task_enabled),
                )
            else:
                # Cron OFF: remember what should be enabled when cron is turned back ON
                db.execute(
                    "UPDATE tasks SET enabled_prev = ? WHERE name = 'disable_expired_users'",
                    (disable_task_enabled,),
                )
                db.execute(
                    "UPDATE tasks SET enabled_prev = ? WHERE name = 'expired_subscription_manager'",
                    (warn_task_enabled,),
                )






            # --------------------------------------------------
            # Log cohérent
            # --------------------------------------------------
            add_log(
                "info",
                "settings",
                "Settings updated",
                {
                    "default_language": new_values["default_language"],
                    "default_subscription_days": new_values["default_subscription_days"],
                    "preavis_days": new_values["preavis_days"],
                    "reminder_days": new_values["reminder_days"],
                },
            )

            session["lang"] = new_values["default_language"]

            flash(get_translator()("settings_saved"), "success")
            return redirect(url_for("settings_page"))

        # ------------------------------
        # GET → RENDER SETTINGS UI
        # ------------------------------
        return render_template(
            "settings/settings.html",
            settings=settings,  
            active_page="settings",
            current_lang=session.get("lang", settings["default_language"]),
            available_languages=get_available_languages(),
            app_version=g.get("app_version", "dev"),
        )


    @app.route("/settings/<section>", methods=["GET"])
    def settings_section_page(section: str):
        db = get_db()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        settings = dict(settings)

        # Map section -> template
        template_map = {
            "general": "settings/settings_general.html",
            "subscription": "settings/settings_subscription.html",
            "notifications": "settings/settings_notifications.html",
            "system": "settings/settings_system.html",
        }

        tpl = template_map.get(section)
        if not tpl:
            return redirect(url_for("settings_page"))

        return render_template(
            tpl,
            settings=settings,
            active_page="settings",
            current_lang=session.get("lang", settings.get("default_language")),
            available_languages=get_available_languages(),
            app_version=g.get("app_version", "dev"),
        )


    # -----------------------------
    # LOGS
    # -----------------------------
    
    def paginate(logs, page, per_page=10):
        start = (page - 1) * per_page
        end = start + per_page
        total_pages = (len(logs) + per_page - 1) // per_page
        return logs[start:end], total_pages

    


