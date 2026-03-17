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
SERVER_DELETE_LOCK = threading.Lock()
SERVER_DELETE_IN_PROGRESS = set()

server_delete_logger = get_logger("server_delete")

SERVER_DELETE_LOCK = threading.Lock()
SERVER_DELETE_IN_PROGRESS = set()

DELETE_BATCH_SIZE = 1000


def _delete_in_chunks(conn, sql, params=(), batch_size=DELETE_BATCH_SIZE):
    total = 0
    while True:
        cur = conn.execute(sql, tuple(params) + (batch_size,))
        deleted = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()

        if deleted <= 0:
            break

        total += deleted

        if deleted < batch_size:
            break

    return total


def _background_delete_server(app, db_path, server_id, server_name):
    delete_key = f"server:{server_id}"
    conn = None

    try:
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")

        server_delete_logger.info(
            f"[server_delete] Start background deletion for server_id={server_id} name={server_name}"
        )

        # 1) Très grosses tables monitoring / jobs
        deleted_sessions = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_sessions
            WHERE rowid IN (
                SELECT rowid
                FROM media_sessions
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_events = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_events
            WHERE rowid IN (
                SELECT rowid
                FROM media_events
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_history = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_session_history
            WHERE rowid IN (
                SELECT rowid
                FROM media_session_history
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_jobs = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_jobs
            WHERE rowid IN (
                SELECT rowid
                FROM media_jobs
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 2) Tables enforcement / identities / imports
        deleted_state = _delete_in_chunks(
            conn,
            """
            DELETE FROM stream_enforcement_state
            WHERE rowid IN (
                SELECT rowid
                FROM stream_enforcement_state
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_enforcements = _delete_in_chunks(
            conn,
            """
            DELETE FROM stream_enforcements
            WHERE rowid IN (
                SELECT rowid
                FROM stream_enforcements
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_identities = _delete_in_chunks(
            conn,
            """
            DELETE FROM user_identities
            WHERE rowid IN (
                SELECT rowid
                FROM user_identities
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_import_jobs = _delete_in_chunks(
            conn,
            """
            DELETE FROM tautulli_import_jobs
            WHERE rowid IN (
                SELECT rowid
                FROM tautulli_import_jobs
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_welcome_templates = _delete_in_chunks(
            conn,
            """
            DELETE FROM welcome_email_templates
            WHERE rowid IN (
                SELECT rowid
                FROM welcome_email_templates
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 3) Liaison libraries -> media_user_libraries
        deleted_mul = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_user_libraries
            WHERE rowid IN (
                SELECT mul.rowid
                FROM media_user_libraries mul
                JOIN libraries l ON l.id = mul.library_id
                WHERE l.server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 4) Libraries puis media_users
        deleted_libraries = _delete_in_chunks(
            conn,
            """
            DELETE FROM libraries
            WHERE rowid IN (
                SELECT rowid
                FROM libraries
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_media_users = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_users
            WHERE rowid IN (
                SELECT rowid
                FROM media_users
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 5) Final : supprimer le serveur
        conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        conn.commit()

        server_delete_logger.info(
            "[server_delete] Done for server_id=%s name=%s | "
            "media_sessions=%s media_events=%s media_session_history=%s media_jobs=%s "
            "stream_enforcement_state=%s stream_enforcements=%s user_identities=%s "
            "tautulli_import_jobs=%s welcome_email_templates=%s "
            "media_user_libraries=%s libraries=%s media_users=%s",
            server_id,
            server_name,
            deleted_sessions,
            deleted_events,
            deleted_history,
            deleted_jobs,
            deleted_state,
            deleted_enforcements,
            deleted_identities,
            deleted_import_jobs,
            deleted_welcome_templates,
            deleted_mul,
            deleted_libraries,
            deleted_media_users,
        )

    except Exception as e:
        server_delete_logger.exception(
            f"[server_delete] Failed for server_id={server_id} name={server_name}: {e}"
        )
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

        with SERVER_DELETE_LOCK:
            SERVER_DELETE_IN_PROGRESS.discard(delete_key)

def register(app):
    @app.route("/servers/<int:server_id>/sync")
    def sync_server(server_id):
        db = get_db()

        # --------------------------------------------------
        # Vérifier que le serveur existe
        # --------------------------------------------------
        server = db.query_one(
            "SELECT id, type FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # Si ce n'est pas un serveur Plex, ne pas créer de job Plex
        # --------------------------------------------------
        if server["type"] != "plex":
            flash("sync_not_supported_for_server_type", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Cibler les vodum_users qui ont AU MOINS 1 accès sur ce serveur
        # (évite le cas où apply_sync_job bloque quand sections == [])
        # --------------------------------------------------
        vodum_users = db.query(
            """
            SELECT DISTINCT vu.id AS vodum_user_id
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            JOIN media_user_libraries mul
                ON mul.media_user_id = mu.id
            JOIN libraries l
                ON l.id = mul.library_id
            WHERE mu.server_id = ?
              AND l.server_id = ?
              AND mu.type = 'plex'
            """,
            (server_id, server_id),
        )

        if not vodum_users:
            flash("no_users_to_sync_for_server", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Créer 1 job sync par vodum_user (dans media_jobs)
        # --------------------------------------------------
        created = 0
        for r in vodum_users:
            vodum_user_id = int(r["vodum_user_id"])
            dedupe_key = f"plex:sync:server={server_id}:vodum_user={vodum_user_id}"

            db.execute(
                """
                INSERT OR IGNORE INTO media_jobs(
                    provider, action,
                    vodum_user_id, server_id, library_id,
                    payload_json,
                    processed, success, attempts,
                    dedupe_key
                )
                VALUES (
                    'plex', 'sync',
                    ?, ?, NULL,
                    NULL,
                    0, 0, 0,
                    ?
                )
                """,
                (vodum_user_id, server_id, dedupe_key),
            )
            # rowcount vaut souvent 1 si insert, 0 si déjà présent (IGNORE)
            try:
                if getattr(db, "last_rowcount", None):
                    pass
            except Exception:
                pass
            created += 1

        # --------------------------------------------------
        # Activer + déclencher apply_plex_access_updates
        # --------------------------------------------------
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name = 'apply_plex_access_updates'
            """
        )

        try:
            from tasks_engine import enqueue_task
            task = db.query_one("SELECT id FROM tasks WHERE name = 'apply_plex_access_updates'")
            if task:
                enqueue_task(task["id"])
        except Exception:
            # pas bloquant, le scheduler la prendra
            pass

        flash("sync_jobs_created", "success")
        return redirect(url_for("server_detail", server_id=server_id))





    @app.route("/servers", methods=["GET"])
    def servers_list():
        db = get_db()

        servers = db.query(
            """
            SELECT
                s.*,

                -- nb bibliothèques
                COUNT(DISTINCT l.id) AS libraries_count,

                -- nb d'utilisateurs Vodum ayant au moins un compte sur ce serveur
                COUNT(DISTINCT mu.vodum_user_id) AS users_count

            FROM servers s
            LEFT JOIN libraries l
                   ON l.server_id = s.id

            LEFT JOIN media_users mu
                   ON mu.server_id = s.id

            GROUP BY s.id
            ORDER BY s.name
            """
        )

        with SERVER_DELETE_LOCK:
            deleting_server_ids = {
                int(str(x).split(":", 1)[1])
                for x in SERVER_DELETE_IN_PROGRESS
                if str(x).startswith("server:")
            }

        with SERVER_DELETE_LOCK:
            deleting_server_ids = {
                int(str(x).split(":", 1)[1])
                for x in SERVER_DELETE_IN_PROGRESS
                if str(x).startswith("server:")
            }

        return render_template(
            "servers/servers.html",
            servers=servers,
            deleting_server_ids=deleting_server_ids,
            active_page="servers",
            active_tab="servers",
        )




    @app.route("/libraries", methods=["GET"])
    def libraries_list():
        db = get_db()

        libraries = db.query(
            """
            SELECT
                l.*,
                s.name AS server_name,

                -- nb d'utilisateurs Vodum ayant accès
                COUNT(DISTINCT mu.vodum_user_id) AS users_count

            FROM libraries l
            JOIN servers s
                ON s.id = l.server_id

            LEFT JOIN media_user_libraries mul
                ON mul.library_id = l.id

            LEFT JOIN media_users mu
                ON mu.id = mul.media_user_id

            GROUP BY l.id
            ORDER BY s.name, l.name
            """
        )

        return render_template(
            "servers/libraries.html",
            libraries=libraries,
            active_page="servers",
            active_tab="libraries",
        )







    @app.route("/servers/new", methods=["POST"])
    def server_create():
        db = get_db()

        server_type = (request.form.get("type") or "generic").lower()
        name = f"{server_type.upper()} - pending"

        url = request.form.get("url") or None
        local_url = request.form.get("local_url") or None
        public_url = request.form.get("public_url") or None
        token = request.form.get("token") or None

        # Options spécifiques (stockées dans settings_json)
        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None

        server_identifier = str(uuid.uuid4())

        # settings_json (clé/valeurs extensibles)
        settings = {}
        if tautulli_url or tautulli_api_key:
            settings["tautulli"] = {"url": tautulli_url, "api_key": tautulli_api_key}
        settings_json = json.dumps(settings) if settings else None

        try:
            # --------------------------------------------------
            # 1) INSERT serveur
            # --------------------------------------------------
            cur = db.execute(
                """
                INSERT INTO servers (
                    name,
                    type,
                    server_identifier,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    server_type,
                    server_identifier,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    "unknown",
                ),
            )
            server_id = getattr(cur, "lastrowid", None)

            # --------------------------------------------------
            # 2) Activation des tâches système
            # --------------------------------------------------
            db.execute(
                """
                UPDATE tasks
                SET enabled = 1,
                    status = CASE
                        WHEN status = 'disabled' THEN 'idle'
                        WHEN status IN ('idle','error','running','queued') THEN status
                        ELSE 'idle'
                    END
                WHERE name IN ('check_servers', 'update_user_status')
                """
            )


            # --------------------------------------------------
            # 3) Commit avant enqueue (évite des incohérences + locks)
            # --------------------------------------------------
            try:
                db.commit()
            except Exception:
                # Si ton get_db() auto-commit déjà, ce commit peut ne pas exister
                # ou lever selon ton wrapper. Dans ce cas, on ignore.
                pass

            # --------------------------------------------------
            # 4) Enchaîner check + sync (FIFO, jamais perdu)
            # --------------------------------------------------
            try:
                if server_type == "plex":
                    run_task_sequence(["check_servers", "sync_plex"])
                elif server_type == "jellyfin":
                    run_task_sequence(["check_servers", "sync_jellyfin"])
                else:
                    run_task_sequence(["check_servers"])
            except Exception as e:
                app.logger.warning(f"Failed to queue sequence after server creation: {e}")


        except Exception as e:
            # Si l'insert serveur ou l'update tasks a planté
            app.logger.exception(f"Server creation failed: {e}")
            flash("server_create_failed", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # 5) Message UI
        # --------------------------------------------------
        if server_type == "plex":
            flash("plex_server_created_sync_planned", "success")
        elif server_type == "jellyfin":
            flash("jellyfin_server_created_sync_planned", "success")
        else:
            flash("server_created_no_sync", "success")

        return redirect(url_for("servers_list"))







    @app.route("/servers/<int:server_id>/delete", methods=["POST"])
    def server_delete(server_id):
        db = get_db()

        server = db.query_one(
            "SELECT id, name FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        delete_key = f"server:{server_id}"

        with SERVER_DELETE_LOCK:
            if delete_key in SERVER_DELETE_IN_PROGRESS:
                flash("server_delete_already_running", "warning")
                return redirect(url_for("servers_list"))

            SERVER_DELETE_IN_PROGRESS.add(delete_key)

        try:
            app_obj = current_app._get_current_object()
            db_path = current_app.config["DATABASE"]

            threading.Thread(
                target=_background_delete_server,
                args=(app_obj, db_path, int(server_id), server["name"]),
                daemon=True,
                name=f"delete-server-{server_id}",
            ).start()

            flash("server_delete_started", "success")

        except Exception as e:
            with SERVER_DELETE_LOCK:
                SERVER_DELETE_IN_PROGRESS.discard(delete_key)

            flash(f"server_delete_failed ({e})", "error")

        return redirect(url_for("servers_list"))






    @app.route("/servers/<int:server_id>", methods=["GET", "POST"])
    def server_detail(server_id):
        db = get_db()

        # ======================================================
        # POST : mise à jour d'un serveur
        # ======================================================
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            server_type = request.form.get("type") or "other"
            url = request.form.get("url") or None
            local_url = request.form.get("local_url") or None
            public_url = request.form.get("public_url") or None
            token = request.form.get("token") or None
            status = request.form.get("status") or None

            # paramètres spécifiques (ex : Tautulli — stockés en JSON)
            tautulli_url = request.form.get("tautulli_url") or None
            tautulli_api_key = request.form.get("tautulli_api_key") or None

            if not name:
                flash("Le nom du serveur est obligatoire", "error")
                return redirect(url_for("server_detail", server_id=server_id))

            # charger l'ancien JSON pour le merger proprement
            row = db.query_one(
                "SELECT settings_json FROM servers WHERE id = ?",
                (server_id,),
            )

            settings = {}
            if row and row["settings_json"]:
                try:
                    settings = json.loads(row["settings_json"])
                except Exception:
                    settings = {}

            # MAJ éventuelle des paramètres spéciaux
            if tautulli_url or tautulli_api_key:
                settings["tautulli"] = {
                    "url": tautulli_url,
                    "api_key": tautulli_api_key,
                }

            settings_json = json.dumps(settings) if settings else None

            # UPDATE (nouveau schéma)
            db.execute(
                """
                UPDATE servers
                SET name = ?,
                    type = ?,
                    url = ?,
                    local_url = ?,
                    public_url = ?,
                    token = ?,
                    settings_json = ?,
                    status = ?
                WHERE id = ?
                """,
                (
                    name,
                    server_type,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    status,
                    server_id,
                ),
            )

            flash("server_updated", "success")
            return redirect(url_for("server_detail", server_id=server_id))

        # ======================================================
        # GET : affichage du serveur
        # ======================================================
        server = db.query_one(
            "SELECT * FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            return "Serveur introuvable", 404

        # --- bibliothèques ---
        libraries = db.query(
            """
            SELECT
                l.*,
                COUNT(DISTINCT mu.vodum_user_id) AS users_count
            FROM libraries l
            LEFT JOIN media_user_libraries mul
                   ON mul.library_id = l.id
            LEFT JOIN media_users mu
                   ON mu.id = mul.media_user_id
            WHERE l.server_id = ?
            GROUP BY l.id
            ORDER BY l.name
            """,
            (server_id,),
        )

        # --- utilisateurs reliés au serveur ---
        users = db.query(
            """
            SELECT
                vu.id,
                vu.username,
                vu.email
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            WHERE mu.server_id = ?
            GROUP BY vu.id
            ORDER BY vu.username
            """,
            (server_id,),
        )

        return render_template(
            "servers/server_detail.html",
            server=server,
            libraries=libraries,
            users=users,
            active_page="servers",
        )




    @app.route("/servers/bulk_grant", methods=["POST"])
    def bulk_grant_libraries():
        db = get_db()

        server_id = request.form.get("server_id", type=int)
        library_ids = request.form.getlist("library_ids")

        if not server_id or not library_ids:
            flash("no_server_or_library_selected", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # Vérifier que c'est bien un serveur Plex
        # --------------------------------------------------
        server = db.query_one("SELECT id, type FROM servers WHERE id = ?", (server_id,))
        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        if server["type"] != "plex":
            flash("sync_not_supported_for_server_type", "warning")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # Nettoyage + cast des lib ids
        # --------------------------------------------------
        try:
            library_ids_int = [int(x) for x in library_ids]
        except ValueError:
            flash("invalid_library", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # Validation : ne garder que les libraries appartenant au server_id
        # (évite les incohérences si l'UI envoie autre chose)
        # --------------------------------------------------
        placeholders = ",".join("?" * len(library_ids_int))
        valid_rows = db.query(
            f"""
            SELECT id
            FROM libraries
            WHERE server_id = ?
              AND id IN ({placeholders})
            """,
            (server_id, *library_ids_int),
        )
        valid_library_ids = [int(r["id"]) for r in valid_rows]

        if not valid_library_ids:
            flash("no_valid_libraries_for_server", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # 1) Utilisateurs ACTIFS liés à ce serveur
        #    + vodum_user_id indispensable pour media_jobs
        # --------------------------------------------------
        users = db.query(
            """
            SELECT mu.id AS media_user_id,
                   mu.vodum_user_id AS vodum_user_id
            FROM media_users mu
            JOIN vodum_users vu ON vu.id = mu.vodum_user_id
            WHERE mu.server_id = ?
              AND mu.type = 'plex'
              AND vu.status = 'active'
            """,
            (server_id,),
        )

        if not users:
            flash("no_active_users_for_server", "warning")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # 2) Donner accès aux bibliothèques (media_user_libraries)
        # --------------------------------------------------
        for lib_id in valid_library_ids:
            for u in users:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (u["media_user_id"], lib_id),
                )

        # --------------------------------------------------
        # 3) Créer des jobs compatibles worker: media_jobs
        #    -> 1 sync par vodum_user (un sync suffit après bulk grant)
        # --------------------------------------------------
        vodum_user_ids = sorted({
            int(u["vodum_user_id"])
            for u in users
            if u["vodum_user_id"] is not None
        })

        for vodum_user_id in vodum_user_ids:
            dedupe_key = f"plex:sync:server={server_id}:vodum_user={vodum_user_id}:bulk_grant"

            payload = {
                "reason": "bulk_grant",
                "library_ids": valid_library_ids,
            }

            db.execute(
                """
                INSERT OR IGNORE INTO media_jobs(
                    provider, action,
                    vodum_user_id, server_id, library_id,
                    payload_json,
                    processed, success, attempts,
                    dedupe_key
                )
                VALUES(
                    'plex', 'sync',
                    ?, ?, NULL,
                    ?,
                    0, 0, 0,
                    ?
                )
                """,
                (vodum_user_id, server_id, json.dumps(payload), dedupe_key),
            )

        # --------------------------------------------------
        # 4) Activer + déclencher apply_plex_access_updates
        # --------------------------------------------------
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name = 'apply_plex_access_updates'
            """
        )

        try:
            row = db.query_one("SELECT id FROM tasks WHERE name='apply_plex_access_updates'")
            if row:
                enqueue_task(row["id"])
        except Exception:
            # pas bloquant si enqueue échoue, le scheduler le prendra
            pass

        flash("grant_access_active_success", "success")
        return redirect(url_for("servers_list", server_id=server_id))




    # -----------------------------
    #  abonnements
    # -----------------------------


