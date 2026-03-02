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
    @app.route("/subscriptions", methods=["GET"])
    def subscriptions():
        db = get_db()
        tab = (request.args.get("tab") or "templates").strip().lower()
        if tab not in ("templates", "applications", "gifts"):
            tab = "templates"

        servers = db.query("SELECT id, name, type FROM servers ORDER BY name") or []
        templates = db.query("SELECT id, name, notes, policies_json, created_at, updated_at FROM subscription_templates ORDER BY name") or []
        templates = [dict(t) for t in templates]
        for t in templates:
            try:
                t['policies_count'] = len(json.loads(t.get('policies_json') or '[]'))
            except Exception:
                t['policies_count'] = 0

        # Users list for applications tab
        users = db.query("""
            SELECT
              vu.id,
              vu.username,
              vu.email,
              vu.status,
              vu.subscription_template_id,
              vu.max_streams_override,
              st.name AS subscription_template_name
            FROM vodum_users vu
            LEFT JOIN subscription_templates st ON st.id = vu.subscription_template_id
            ORDER BY LOWER(COALESCE(vu.username, '')) ASC, vu.id ASC
        """) or []
        users = [dict(u) for u in users]

        return render_template(
            "subscriptions/subscriptions.html",
            tab=tab,
            servers=servers,
            templates=templates,
            users=users,
        )




    

    # -----------------------------
    # TEMPLATES (CRUD)
    # -----------------------------

    def _parse_json_list(raw: str):
        try:
            v = json.loads(raw or "[]")
            return v if isinstance(v, list) else []
        except Exception:
            return []

    @app.post("/subscriptions/templates/save")
    def subscription_templates_save():
        db = get_db()
        template_id_raw = (request.form.get("template_id") or "").strip()
        template_id = int(template_id_raw) if template_id_raw.isdigit() else None

        name = (request.form.get("name") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        policies_json = (request.form.get("policies_json") or "[]").strip()
        policies = _parse_json_list(policies_json)

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
                "UPDATE subscription_templates SET name=?, notes=?, policies_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, notes, json.dumps(clean), template_id),
            )
            add_log(db, "subscriptions", f"Template updated: {name} (id={template_id})")
            flash("subscription_template_saved", "success")
        else:
            # Create
            dup = db.query_one("SELECT id FROM subscription_templates WHERE name = ?", (name,))
            if dup:
                flash("subscription_template_name_exists", "error")
                return redirect(url_for("subscriptions", tab="templates"))

            db.execute(
                "INSERT INTO subscription_templates(name, notes, policies_json) VALUES (?, ?, ?)",
                (name, notes, json.dumps(clean)),
            )
            add_log(db, "subscriptions", f"Template created: {name}")
            flash("subscription_template_created", "success")

        return redirect(url_for("subscriptions", tab="templates"))

    @app.post("/subscriptions/templates/<int:template_id>/duplicate")
    def subscription_templates_duplicate(template_id: int):
        db = get_db()
        tpl = db.query_one("SELECT * FROM subscription_templates WHERE id=?", (template_id,))
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
            "INSERT INTO subscription_templates(name, notes, policies_json) VALUES (?, ?, ?)",
            (new_name, tpl.get("notes") or "", tpl.get("policies_json") or "[]"),
        )
        add_log(db, "subscriptions", f"Template duplicated: {base_name} -> {new_name}")
        flash("subscription_template_duplicated", "success")
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
        add_log(db, "subscriptions", f"Template deleted: {name} (id={template_id})")
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

        # ✅ Auto-enable stream_enforcer if at least one policy is enabled
        if any_enabled:
            db.execute("""
                UPDATE tasks
                SET enabled = 1,
                    status = CASE WHEN status = 'disabled' THEN 'idle' ELSE status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE name = 'stream_enforcer'
            """)

        return tname

    @app.post("/subscriptions/apply/user")
    def subscription_apply_user():
        db = get_db()
        user_id_raw = (request.form.get("user_id") or "").strip()
        template_id_raw = (request.form.get("template_id") or "").strip()
        confirm = (request.form.get("confirm_replace") or "0") == "1"

        if not user_id_raw.isdigit() or not template_id_raw.isdigit():
            flash("subscription_apply_invalid", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        user_id = int(user_id_raw)
        template_id = int(template_id_raw)

        u = db.query_one("SELECT subscription_template_id FROM vodum_users WHERE id=?", (user_id,))
        existing_id = int(u["subscription_template_id"]) if (u and u["subscription_template_id"] is not None) else None

        if existing_id and existing_id != template_id and not confirm:
            flash("subscription_apply_replace_warning", "warning")
            return redirect(url_for("subscriptions", tab="applications"))

        try:
            tname = _apply_template_snapshot(db, user_id, template_id)
        except ValueError:
            flash("subscription_template_not_found", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        add_log(db, "subscriptions", f"Template applied to user #{user_id}: {tname} (template_id={template_id})")
        flash("subscription_apply_success", "success")
        return redirect(url_for("subscriptions", tab="applications"))

    @app.post("/subscriptions/apply/server")
    def subscription_apply_server_bulk():
        db = get_db()
        server_id_raw = (request.form.get("server_id") or "").strip()
        template_id_raw = (request.form.get("template_id") or "").strip()
        confirm = (request.form.get("confirm_replace") or "0") == "1"

        if not server_id_raw.isdigit() or not template_id_raw.isdigit():
            flash("subscription_apply_invalid", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        server_id = int(server_id_raw)
        template_id = int(template_id_raw)

        # Find users linked to this server
        rows = db.query(
            "SELECT DISTINCT vodum_user_id FROM media_users WHERE server_id=? AND vodum_user_id IS NOT NULL",
            (server_id,),
        ) or []
        user_ids = [int(r["vodum_user_id"]) for r in rows if r.get("vodum_user_id")]

        if not user_ids:
            flash("subscription_apply_no_users", "warning")
            return redirect(url_for("subscriptions", tab="applications"))

        # Optional: if not confirmed and at least one user already has a template, warn
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
            tpl = db.query_one("SELECT name FROM subscription_templates WHERE id=?", (template_id,))
            tname = (tpl["name"] if tpl else "")
            for uid in user_ids:
                _apply_template_snapshot(db, uid, template_id)
                applied += 1
        except Exception:
            flash("subscription_apply_failed", "error")
            return redirect(url_for("subscriptions", tab="applications"))

        add_log(db, "subscriptions", f"Template bulk-applied to server #{server_id}: {tname} (template_id={template_id}) to {applied} users")
        flash("subscription_apply_bulk_success", "success")
        return redirect(url_for("subscriptions", tab="applications"))
# -----------------------------
    # TÂCHES
    # -----------------------------
    


