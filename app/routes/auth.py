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
from datetime import datetime, timezone, timedelta
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
from app import RESET_MAGIC, RESET_FILE

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg

task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")


AUTH_BRUTEFORCE_MAX_ATTEMPTS = max(1, int(os.environ.get("VODUM_AUTH_MAX_ATTEMPTS", "5")))
AUTH_BRUTEFORCE_WINDOW_MINUTES = max(1, int(os.environ.get("VODUM_AUTH_WINDOW_MINUTES", "15")))
AUTH_BRUTEFORCE_LOCK_MINUTES = max(1, int(os.environ.get("VODUM_AUTH_LOCK_MINUTES", "15")))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_sql(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _sql_to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _client_ip() -> str:
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return (request.remote_addr or "unknown").strip()


def _ensure_login_attempt_row(db, scope: str, scope_value: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO auth_login_attempts(scope, scope_value, failed_attempts)
        VALUES (?, ?, 0)
        """,
        (scope, scope_value),
    )


def _get_login_attempt_row(db, scope: str, scope_value: str) -> dict:
    _ensure_login_attempt_row(db, scope, scope_value)
    row = db.query_one(
        """
        SELECT scope, scope_value, failed_attempts, first_failed_at, last_failed_at, locked_until
        FROM auth_login_attempts
        WHERE scope = ? AND scope_value = ?
        """,
        (scope, scope_value),
    )
    return dict(row) if row else {
        "scope": scope,
        "scope_value": scope_value,
        "failed_attempts": 0,
        "first_failed_at": None,
        "last_failed_at": None,
        "locked_until": None,
    }


def _remaining_lock_seconds(row: dict, now: datetime) -> int:
    locked_until = _sql_to_dt(row.get("locked_until"))
    if not locked_until or locked_until <= now:
        return 0
    return int((locked_until - now).total_seconds())


def _register_failed_login(db, scope: str, scope_value: str, now: datetime) -> None:
    row = _get_login_attempt_row(db, scope, scope_value)

    first_failed_at = _sql_to_dt(row.get("first_failed_at"))
    window_seconds = AUTH_BRUTEFORCE_WINDOW_MINUTES * 60

    if first_failed_at is None or (now - first_failed_at).total_seconds() > window_seconds:
        failed_attempts = 1
        first_failed_at = now
    else:
        failed_attempts = int(row.get("failed_attempts") or 0) + 1

    locked_until = None
    if failed_attempts >= AUTH_BRUTEFORCE_MAX_ATTEMPTS:
        locked_until = now + timedelta(minutes=AUTH_BRUTEFORCE_LOCK_MINUTES)

    db.execute(
        """
        UPDATE auth_login_attempts
        SET
            failed_attempts = ?,
            first_failed_at = ?,
            last_failed_at = ?,
            locked_until = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND scope_value = ?
        """,
        (
            failed_attempts,
            _dt_to_sql(first_failed_at),
            _dt_to_sql(now),
            _dt_to_sql(locked_until) if locked_until else None,
            scope,
            scope_value,
        ),
    )


def _reset_failed_login(db, scope: str, scope_value: str) -> None:
    db.execute(
        """
        UPDATE auth_login_attempts
        SET
            failed_attempts = 0,
            first_failed_at = NULL,
            last_failed_at = NULL,
            locked_until = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND scope_value = ?
        """,
        (scope, scope_value),
    )


def _is_login_locked(db, scope: str, scope_value: str, now: datetime) -> tuple[bool, int]:
    row = _get_login_attempt_row(db, scope, scope_value)
    remaining = _remaining_lock_seconds(row, now)

    if remaining <= 0 and row.get("locked_until"):
        _reset_failed_login(db, scope, scope_value)
        return False, 0

    return remaining > 0, remaining


def _login_failed(db, email: str, client_ip: str, reason: str) -> None:
    now = _utcnow()
    _register_failed_login(db, "ip", client_ip, now)
    if email:
        _register_failed_login(db, "email", email, now)

    auth_logger.warning(
        "AUTH login failed reason=%s email=%s ip=%s ua=%s",
        reason,
        email or "<empty>",
        client_ip,
        request.user_agent.string,
    )


def _login_locked_response(email: str, client_ip: str, remaining_seconds: int):
    remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
    flash(
        f"Trop de tentatives de connexion. Réessayez dans {remaining_minutes} minute(s).",
        "error",
    )
    auth_logger.warning(
        "AUTH login blocked email=%s ip=%s remaining_seconds=%s ua=%s",
        email or "<empty>",
        client_ip,
        remaining_seconds,
        request.user_agent.string,
    )
    return redirect(url_for("login"))


def register(app):
    @app.route("/setup-admin", methods=["GET", "POST"])
    def setup_admin():
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        # déjà configuré => go login/home
        if (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("login"))

        if request.method == "POST":
            # Récupération + normalisation (ne plante jamais)
            email_input = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "")

            # ✅ Stricte: email obligatoire.
            # Si l'utilisateur laisse vide MAIS qu'un email existe déjà en DB, on le reprend.
            email = email_input or (s.get("admin_email") or "").strip().lower()

            # ✅ Validation stricte (pas seulement "@")
            # - non vide
            # - contient exactement un "@"
            # - pas d'espaces
            # - a un domaine avec un "."
            if (
                not email
                or " " in email
                or email.count("@") != 1
                or "." not in email.split("@", 1)[1]
            ):
                flash("Un email admin valide est obligatoire.", "error")
                return redirect(url_for("setup_admin"))

            # ✅ Mot de passe strict
            if len(password) < 8:
                flash("Mot de passe trop court (8 caractères minimum).", "error")
                return redirect(url_for("setup_admin"))

            pwd_hash = generate_password_hash(password)

            db.execute(
                "UPDATE settings SET admin_email = ?, admin_password_hash = ?, auth_enabled = 1 WHERE id = 1",
                (email, pwd_hash),
            )

            session.clear()
            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = email
            session.permanent = True

            # ensuite seulement, si aucun serveur -> page serveurs
            row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
            if row and int(row["cnt"] or 0) == 0:
                return redirect(url_for("servers_list"))

            return redirect(url_for("dashboard"))

        return render_template(
            "auth/setup_admin.html",
            admin_email=(s.get("admin_email") or "")
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        if not (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("setup_admin"))

        if request.method == "POST":
            now = _utcnow()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            client_ip = _client_ip()

            locked_ip, remaining_ip = _is_login_locked(db, "ip", client_ip, now)
            if locked_ip:
                return _login_locked_response(email, client_ip, remaining_ip)

            if email:
                locked_email, remaining_email = _is_login_locked(db, "email", email, now)
                if locked_email:
                    return _login_locked_response(email, client_ip, remaining_email)

            expected_email = (s.get("admin_email") or "").strip().lower()
            if not email or email != expected_email:
                _login_failed(db, email, client_ip, "bad_email")
                flash("Email ou mot de passe incorrect.", "error")
                return redirect(url_for("login"))

            if not check_password_hash(s["admin_password_hash"], password):
                _login_failed(db, email, client_ip, "bad_password")
                flash("Email ou mot de passe incorrect.", "error")
                return redirect(url_for("login"))

            _reset_failed_login(db, "ip", client_ip)
            _reset_failed_login(db, "email", email)

            session.clear()
            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = email
            session.permanent = True

            next_url = request.args.get("next") or url_for("dashboard")
            auth_logger.info("AUTH login ok email=%s ip=%s ua=%s", email, client_ip, request.user_agent.string)
            return redirect(next_url)

        reset_host_example = os.environ.get(
            "VODUM_RESET_FILE_EXAMPLE",
            "/mnt/user/appdata/VODUM/password.reset"
        )
        reset_cmd = f'echo "{RESET_MAGIC}" > {reset_host_example}'

        return render_template(
            "auth/login.html",
            reset_available=os.path.exists(RESET_FILE),
            reset_cmd=reset_cmd,
        )

    @app.route("/logout")
    def logout():
        session.clear()
        auth_logger.info("AUTH logout ip=%s ua=%s", _client_ip(), request.user_agent.string)
        return redirect(url_for("login"))

    # -----------------------------
    # SETTINGS / PARAMÈTRES
    # -----------------------------
    @app.before_request
    def setup_guard_no_servers():
        """
        Mode "setup" : si aucun serveur n'est configuré, on force l'accès
        uniquement à la page serveurs pour permettre l'initialisation.
        """
        allowed_prefixes = (
            "/static",
            "/set_language",
            "/servers",
            "/servers/new",
            "/api/tasks/activity",
            "/health",
            "/login",
            "/logout",
            "/setup-admin",
        )

        if request.path.startswith(allowed_prefixes):
            return

        if request.path in ("/favicon.ico",):
            return

        db = get_db()

        try:
            exists = db.query_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='servers'"
            )
            if not exists:
                return redirect(url_for("servers_list"))
        except Exception:
            return

        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("servers_list"))

    @app.before_request
    def maintenance_guard():
        allowed_prefixes = (
            "/static",
            "/set_language",
            "/health",
            "/login",
            "/logout",
            "/setup-admin",
        )

        if request.path.startswith(allowed_prefixes) or request.path in ("/favicon.ico",):
            return

        try:
            db = get_db()
            row = db.query_one("SELECT maintenance_mode FROM settings WHERE id = 1")
            if row and int(row["maintenance_mode"] or 0) == 1:
                return (
                    render_template("maintenance.html", active_page="settings"),
                    503,
                )
        except Exception:
            return