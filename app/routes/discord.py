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
from discord_utils import is_discord_ready, enrich_discord_settings, validate_discord_bot_token, fetch_discord_bot_identity
from core.i18n import get_translator, get_available_languages
from core.backup import BackupConfig, ensure_backup_dir, create_backup_file, list_backups, restore_backup_file
from werkzeug.security import generate_password_hash, check_password_hash

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg

task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

def register(app):
    @app.route("/discord")
    def discord_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")

        if is_discord_ready(settings):
            return redirect(url_for("discord_campaigns_page"))

        return redirect(url_for("discord_settings_page"))


    @app.route("/discord/settings", methods=["GET", "POST"])
    def discord_settings_page():
        db = get_db()

        settings_row = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings_row) if settings_row else {}

        # Active bot (if any)
        active_bot = None
        active_bot_id = settings.get("discord_bot_id")
        try:
            active_bot_id = int(active_bot_id) if active_bot_id not in (None, "", 0, "0") else None
        except Exception:
            active_bot_id = None

        if active_bot_id:
            try:
                row = db.query_one("SELECT * FROM discord_bots WHERE id = ?", (active_bot_id,))
                active_bot = dict(row) if row else None
            except Exception:
                active_bot = None

        if request.method == "POST":
            action = (request.form.get("action") or "").strip() or "noop"

            # -------------------------------------------------
            # Delete active bot
            # -------------------------------------------------
            if action == "delete_bot":
                if not active_bot_id:
                    flash("No active bot to delete", "error")
                    return redirect(url_for("discord_settings_page"))

                # Disable discord + clear selected bot/token
                db.execute(
                    """
                    UPDATE settings
                    SET discord_enabled = 0, discord_bot_id = NULL, discord_bot_token = NULL
                    WHERE id = 1
                    """
                )

                # Disable Discord tasks
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = 0,
                        status  = 'disabled'
                    WHERE name IN ('send_expiration_discord', 'send_campaign_discord')
                    """
                )

                try:
                    db.execute("DELETE FROM discord_bots WHERE id = ?", (active_bot_id,))
                    flash("Bot deleted", "success")
                except Exception as e:
                    flash(f"Failed to delete bot: {e}", "error")

                return redirect(url_for("discord_settings_page"))

            # -------------------------------------------------
            # Connect with token (validates + stores + selects)
            # -------------------------------------------------
            if action == "connect_token":
                bot_token = (request.form.get("bot_token") or "").strip()
                bot_name = (request.form.get("bot_name") or "").strip() or None

                if not bot_token:
                    flash("Missing bot token", "error")
                    return redirect(url_for("discord_settings_page"))

                ok, data = fetch_discord_bot_identity(bot_token)
                if not ok:
                    flash(f"Discord token invalid: {data.get('error') or data}", "error")
                    return redirect(url_for("discord_settings_page"))

                bot_user_id = data.get("id")
                bot_username = data.get("global_name") or data.get("username")

                # Default name: bot username
                if not bot_name:
                    bot_name = bot_username or "Discord Bot"

                # If a bot is already selected, update it. Else create a new bot and select it.
                target_bot_id = active_bot_id

                try:
                    if target_bot_id:
                        db.execute(
                            """
                            UPDATE discord_bots
                            SET name=?, token=?, bot_user_id=?, bot_username=?, updated_at=CURRENT_TIMESTAMP
                            WHERE id=?
                            """,
                            (bot_name, bot_token, bot_user_id, bot_username, target_bot_id),
                        )
                    else:
                        db.execute(
                            """
                            INSERT INTO discord_bots(name, token, bot_user_id, bot_username, bot_type)
                            VALUES(?, ?, ?, ?, 'custom')
                            """,
                            (bot_name, bot_token, bot_user_id, bot_username),
                        )
                        row = db.query_one("SELECT last_insert_rowid() AS id")
                        target_bot_id = int(dict(row).get("id") or 0)

                    # Select it + enable Discord
                    db.execute(
                        """
                        UPDATE settings
                        SET discord_enabled = 1, discord_bot_id = ?, discord_bot_token = ?
                        WHERE id = 1
                        """,
                        (target_bot_id, bot_token),
                    )

                    # Enable Discord tasks
                    db.execute(
                        """
                        UPDATE tasks
                        SET enabled = 1,
                            status  = 'idle'
                        WHERE name IN ('send_expiration_discord', 'send_campaign_discord')
                        """
                    )

                    add_log("info", "discord", "Discord bot connected")
                    flash(f"Discord bot validated: {bot_username}", "success")
                except Exception as e:
                    flash(f"Failed to save bot: {e}", "error")

                return redirect(url_for("discord_settings_page"))

            return redirect(url_for("discord_settings_page"))

        # GET: enrich settings for display
        settings = enrich_discord_settings(db, settings)

        # Resolve "connected as" best-effort (from effective token)
        if (settings.get("discord_bot_token_effective") or "").strip():
            ok, data = fetch_discord_bot_identity(settings.get("discord_bot_token_effective") or "")
            if ok:
                bot_name = data.get("global_name") or data.get("username")
                settings["discord_bot_username_effective"] = bot_name

                # persist into active bot row (best-effort)
                if active_bot_id:
                    try:
                        db.execute(
                            "UPDATE discord_bots SET bot_user_id=?, bot_username=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (data.get("id"), bot_name, int(active_bot_id)),
                        )
                    except Exception:
                        pass

        # Refresh active bot (in case settings were changed elsewhere)
        try:
            settings_row = db.query_one("SELECT * FROM settings WHERE id = 1")
            settings = dict(settings_row) if settings_row else settings
        except Exception:
            pass
        settings = enrich_discord_settings(db, settings)

        active_bot_id = settings.get("discord_bot_id")
        try:
            active_bot_id = int(active_bot_id) if active_bot_id not in (None, "", 0, "0") else None
        except Exception:
            active_bot_id = None

        active_bot = None
        if active_bot_id:
            try:
                row = db.query_one("SELECT * FROM discord_bots WHERE id = ?", (active_bot_id,))
                active_bot = dict(row) if row else None
            except Exception:
                active_bot = None

        return render_template(
            "discord/discord_settings.html",
            settings=settings,
            active_bot=active_bot,
            active_page="discord",
        )



    @app.route("/discord/templates", methods=["GET", "POST"])
    def discord_templates_page():
        db = get_db()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        if request.method == "POST":
            for ttype in ("preavis", "relance", "fin"):
                title = request.form.get(f"title_{ttype}") or ""
                body = request.form.get(f"body_{ttype}") or ""

                db.execute(
                    """
                    UPDATE discord_templates
                    SET title = ?, body = ?
                    WHERE type = ?
                    """,
                    (title, body, ttype),
                )

            add_log("info", "discord", "Discord templates updated")
            flash("saved", "success")
            return redirect(url_for("discord_templates_page"))

        templates = {row["type"]: dict(row) for row in db.query("SELECT * FROM discord_templates")}

        return render_template(
            "discord/discord_templates.html",
            settings=settings,
            templates=templates,
            active_page="discord",
        )



    @app.route("/discord/campaigns", methods=["GET", "POST"])
    def discord_campaigns_page():
        db = get_db()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        # Fetch list of servers for dropdown (READ)
        servers = db.query("SELECT id, name FROM servers ORDER BY name")

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            body = (request.form.get("body") or "").strip()
            raw_server_id = (request.form.get("server_id") or "").strip()

            if not title or not body:
                flash("missing_fields", "error")
                return redirect(url_for("discord_campaigns_page"))

            server_id = None
            if raw_server_id:
                try:
                    server_id = int(raw_server_id)
                except Exception:
                    server_id = None

            db.execute(
                """
                INSERT INTO discord_campaigns(title, body, server_id, status)
                VALUES (?, ?, ?, 'pending')
                """,
                (title, body, server_id),
            )

            # Optionally enqueue immediately if task enabled
            run_task_by_name("send_campaign_discord")

            add_log("info", "discord", "Discord campaign created")
            flash("saved", "success")
            return redirect(url_for("discord_campaigns_page"))

        campaigns = db.query(
            """
            SELECT c.*, s.name AS server_name
            FROM discord_campaigns c
            LEFT JOIN servers s ON s.id = c.server_id
            ORDER BY c.created_at DESC
            LIMIT 200
            """
        )

        return render_template(
            "discord/discord_campaigns.html",
            settings=settings,
            servers=servers,
            campaigns=campaigns,
            active_page="discord",
        )


    @app.post("/discord/campaigns/delete")
    def discord_campaigns_delete():
        db = get_db()
        cid = request.form.get("id")
        try:
            db.execute("DELETE FROM discord_campaigns WHERE id = ?", (cid,))
            flash("deleted", "success")
        except Exception:
            flash("error", "error")
        return redirect(url_for("discord_campaigns_page"))



    @app.route("/discord/history")
    def discord_history_page():
        backup_cfg = get_backup_cfg()
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        rows = db.query(
            """
            SELECT sd.id, sd.template_type, sd.expiration_date, sd.sent_at,
                   u.id AS user_id, u.username, u.discord_user_id, u.discord_name
            FROM sent_discord sd
            JOIN vodum_users u ON u.id = sd.user_id
            ORDER BY sd.sent_at DESC
            LIMIT 300
            """
        )

        return render_template(
            "discord/discord_history.html",
            settings=settings,
            rows=rows,
            active_page="discord",
        )




    # -----------------------------
    # BACKUP
    # -----------------------------
    def restore_db_file(backup_path: Path):
        db_path = Path(app.config["DATABASE"])

        if not backup_path.exists():
            raise FileNotFoundError(str(backup_path))

        # Sauvegarde de précaution
        backup_dir = ensure_backup_dir(backup_cfg)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        if db_path.exists():
            shutil.copy2(db_path, backup_dir / f"pre_restore_{timestamp}.sqlite")

        # Nettoyer WAL/SHM (sinon SQLite peut repartir avec un état incohérent)
        for suffix in ("-wal", "-shm"):
            p = db_path.with_name(db_path.name + suffix)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # Copie atomique: tmp -> replace
        tmp_path = db_path.with_name(db_path.name + f".tmp_restore_{timestamp}")
        shutil.copy2(backup_path, tmp_path)
        os.replace(tmp_path, db_path)



    def safe_restore(backup_path: Path):
        """
        Restore the SQLite database from a backup file safely.

        - Close current DB (and reset singleton via DBManager.close())
        - Replace DB atomically
        - Remove WAL/SHM (important with SQLite)
        - Re-open a fresh connection to set maintenance_mode=1 and disable tasks
        - Exit the process to let Docker restart the container
        """
        log = get_logger("backup")

        db_path = Path(current_app.config["DATABASE"])
        backup_path = Path(backup_path)

        if not backup_path.exists():
            raise FileNotFoundError(str(backup_path))

        # 1) Close current request DB connection (if any) and remove it from Flask.g
        try:
            db = g.pop("db", None)
            if db is not None:
                try:
                    db.close()  # must reset singleton in DBManager.close()
                except Exception:
                    pass
        except Exception:
            pass

        # 2) Remove SQLite WAL/SHM (avoid inconsistent state after swap)
        for suffix in ("-wal", "-shm"):
            p = db_path.with_name(db_path.name + suffix)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # 3) Atomic replace (copy to temp then os.replace)
        tmp_path = db_path.with_suffix(db_path.suffix + ".restore_tmp")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

        shutil.copy2(str(backup_path), str(tmp_path))
        os.replace(str(tmp_path), str(db_path))

        # 4) Open a FRESH connection on the restored DB and force maintenance + disable tasks
        try:
            restored_db = DBManager(str(db_path))  # new singleton instance created now
            restored_db.execute("UPDATE settings SET maintenance_mode = 1 WHERE id = 1")
            restored_db.execute("UPDATE tasks SET enabled = 0")
            try:
                restored_db.close()  # resets singleton again (safe)
            except Exception:
                pass
        except Exception:
            log.exception("Post-restore maintenance/tasks update failed")

        # 5) Restart container (give time to return response)
        def _delayed_exit():
            time.sleep(1.5)
            os._exit(0)

        threading.Thread(target=_delayed_exit, daemon=True).start()
        log.warning("Database restored. Maintenance mode ON. Process will exit for restart.")




    def get_sqlite_db_size_bytes(db_path: str) -> int | None:
        """
        Retourne la taille disque de la DB SQLite.
        Inclut le fichier -wal / -shm si présents (utile si WAL activé).
        """
        try:
            p = Path(db_path)
            if not p.exists():
                return None

            total = p.stat().st_size

            wal = p.with_name(p.name + "-wal")
            shm = p.with_name(p.name + "-shm")

            if wal.exists():
                total += wal.stat().st_size
            if shm.exists():
                total += shm.stat().st_size

            return int(total)
        except Exception:
            return None
    

    def _looks_like_tautulli_db(path: str) -> tuple[bool, str]:
        """
        Returns (ok, details). details contains tables count or the exception message.
        """
        try:
            import sqlite3

            # Ouvre en lecture seule (évite toute création implicite)
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cur.fetchall()}
            conn.close()

            required = {"users", "session_history", "session_history_metadata"}
            missing = sorted(list(required - tables))
            if missing:
                return False, f"Missing required tables: {', '.join(missing)} (found={len(tables)})"
            return True, f"OK (found_tables={len(tables)})"

        except Exception as e:
            return False, f"{type(e).__name__}: {e}"





