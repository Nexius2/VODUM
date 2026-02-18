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
from app import RESET_MAGIC, RESET_FILE

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg

task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

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

            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = email

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
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            if not email or email != (s.get("admin_email") or "").strip().lower():
                flash("Email ou mot de passe incorrect.", "error")
                return redirect(url_for("login"))

            if not check_password_hash(s["admin_password_hash"], password):
                flash("Email ou mot de passe incorrect.", "error")
                return redirect(url_for("login"))

            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = email

            next_url = request.args.get("next") or url_for("dashboard")
            auth_logger.info("AUTH login ok email=%s ip=%s ua=%s", email, request.remote_addr, request.user_agent.string)
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
        auth_logger.info("AUTH logout ip=%s ua=%s", request.remote_addr, request.user_agent.string)
        return redirect(url_for("login"))

 


    # -----------------------------
    # SETTINGS / PARAMÈTRES
    # -----------------------------
    @app.before_request
    def setup_guard_no_servers():
        """
        Mode "setup" : si aucun serveur n'est configuré, on force l'accès
        uniquement à la page serveurs pour permettre l'initialisation.

        Ne rentre pas en conflit avec un futur système d'auth admin :
        - on laisse passer /login (si tu l'ajoutes plus tard)
        - et on peut ajuster facilement une whitelist.
        """
        # Routes toujours autorisées (setup)
        allowed_prefixes = (
            "/static",
            "/set_language",
            "/servers",       # liste + detail
            "/servers/new",   # création
            "/api/tasks/activity",  # optionnel (évite du bruit console UI)
            "/health",        # optionnel si tu as un healthcheck
            "/login",         # futur admin login
            "/logout",        # futur admin logout
            "/setup-admin",
        )

        if request.path.startswith(allowed_prefixes):
            return

        # On évite de bloquer les fichiers favicon & co
        if request.path in ("/favicon.ico",):
            return

        db = get_db()

        # Si la table servers n'existe pas encore, on considère "setup"
        try:
            exists = db.query_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='servers'"
            )
            if not exists:
                return redirect(url_for("servers_list"))
        except Exception:
            # si DB indispo, on ne force pas ici
            return

        # Si aucun serveur → setup mode actif
        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("servers_list"))
    
    @app.before_request
    def maintenance_guard():
        # Autorisations minimales (maintenance)
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
            # Si DB KO, on évite de faire planter toutes les routes ici.
            return

            
            


