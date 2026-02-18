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
from .users_list import merge_vodum_users


task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

def register(app):
    @app.route("/users/<int:user_id>/plex/share/filter", methods=["POST"])
    def update_plex_share_filter(user_id):
        db = get_db()
        form = request.form

        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        value = (form.get("value") or "").strip()

        allowed_fields = {"filterMovies", "filterTelevision", "filterMusic"}
        if field not in allowed_fields:
            flash("invalid_field", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        mu = db.query_one(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
              AND mu.vodum_user_id = ?
              AND mu.server_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (media_user_id, user_id, server_id),
        )
        if not mu:
            flash("media_user_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        try:
            details = json.loads(mu["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share[field] = value
        details["plex_share"] = plex_share

        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(mu["id"])),
        )

        return redirect(url_for("user_detail", user_id=user_id))



    @app.route("/users/<int:user_id>/plex/share/toggle", methods=["POST"])
    def toggle_plex_share_option(user_id):
        db = get_db()
        form = request.form

        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        vals = form.getlist("value")
        v = vals[-1] if vals else "0"

        truthy = {"1", "true", "on", "yes"}
        new_val = 1 if str(v).strip().lower() in truthy else 0

        allowed_fields = {"allowSync", "allowCameraUpload", "allowChannels"}
        if field not in allowed_fields:
            flash("invalid_field", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # sécurité: s'assurer que ce media_user appartient bien au user_id + server_id
        mu = db.query_one(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
              AND mu.vodum_user_id = ?
              AND mu.server_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (media_user_id, user_id, server_id),
        )
        if not mu:
            flash("media_user_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # load json
        try:
            details = json.loads(mu["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share[field] = new_val
        details["plex_share"] = plex_share

        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(mu["id"])),
        )

        # Optionnel mais recommandé: réplication même owner + jobs
        # -> tu peux réutiliser exactement ta logique existante
        #    (celle de replicate_plex_flags_same_owner + création media_jobs + queue task)

        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id))



    @app.route("/users/<int:user_id>/merge", methods=["POST"])
    def user_merge(user_id):
        db = get_db()

        other_id = request.form.get("other_id", type=int)
        if not other_id:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        if other_id == user_id:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        try:
            merge_vodum_users(db, master_id=user_id, other_id=other_id)
            flash("user_merged", "success")
        except Exception as e:
            task_logger.error(f"[MERGE] error master={user_id} other={other_id}: {e}", exc_info=True)
            flash("merge_failed", "error")

        return redirect(url_for("user_detail", user_id=user_id))






    @app.route("/users/<int:user_id>/toggle_library", methods=["POST"])
    def user_toggle_library(user_id):
        db = get_db()

        library_id = request.form.get("library_id", type=int)
        if not library_id:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------
        # Récup library + server (pour savoir sur quel serveur on agit)
        # --------------------------------------------------
        lib = db.query_one(
            "SELECT id, server_id, name FROM libraries WHERE id = ?",
            (library_id,),
        )
        if not lib:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        server = db.query_one(
            "SELECT id, type, name FROM servers WHERE id = ?",
            (lib["server_id"],),
        )
        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------
        # IMPORTANT : on ne doit toggler QUE les media_users
        # de CE serveur (sinon tu peux lier une lib Plex à un compte Jellyfin)
        # --------------------------------------------------
        media_users = db.query(
            """
            SELECT id
            FROM media_users
            WHERE vodum_user_id = ?
              AND server_id = ?
            """,
            (user_id, lib["server_id"]),
        )
        if not media_users:
            flash("no_media_accounts_for_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        media_user_ids = [mu["id"] for mu in media_users]
        placeholders = ",".join("?" * len(media_user_ids))

        # --------------------------------------------------
        # Vérifier si l'accès existe déjà
        # --------------------------------------------------
        exists = db.query_one(
            f"""
            SELECT 1
            FROM media_user_libraries
            WHERE library_id = ?
              AND media_user_id IN ({placeholders})
            LIMIT 1
            """,
            (library_id, *media_user_ids),
        )

        removed = False

        # --------------------------------------------------
        # TOGGLE en DB
        # --------------------------------------------------
        if exists:
            db.execute(
                f"""
                DELETE FROM media_user_libraries
                WHERE library_id = ?
                  AND media_user_id IN ({placeholders})
                """,
                (library_id, *media_user_ids),
            )
            removed = True
            flash("library_access_removed", "success")
        else:
            for mid in media_user_ids:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (mid, library_id),
                )
            flash("library_access_added", "success")

        # --------------------------------------------------
        # Création d'un job pour apply_plex_access_updates
        # -> uniquement si serveur Plex (pour Jellyfin on fera plus tard)
        # --------------------------------------------------
        if server["type"] == "plex":
            # Combien de libs restent pour CE user sur CE serveur ?
            remaining = db.query_one(
                f"""
                SELECT COUNT(DISTINCT mul.library_id) AS c
                FROM media_user_libraries mul
                JOIN libraries l ON l.id = mul.library_id
                WHERE mul.media_user_id IN ({placeholders})
                  AND l.server_id = ?
                """,
                (*media_user_ids, lib["server_id"]),
            )
            remaining_count = int(remaining["c"] or 0)

            # --------------------------------------------------
            # Choix de l'action:
            # - Ajout d'une bibliothèque => grant (équivalent plex_api_share.py --add --libraries X)
            # - Retrait d'une bibliothèque => sync (réapplique la liste DB), ou revoke si plus rien
            # --------------------------------------------------
            if removed and remaining_count == 0:
                action = "revoke"
                job_library_id = None
                dedupe_key = f"plex:revoke:server={lib['server_id']}:user={user_id}"
            elif removed:
                action = "sync"
                job_library_id = None
                dedupe_key = f"plex:sync:server={lib['server_id']}:user={user_id}"
            else:
                action = "grant"
                job_library_id = library_id
                dedupe_key = f"plex:grant:server={lib['server_id']}:user={user_id}:lib={library_id}"

            payload = {
                "reason": "library_toggle",
                "library_id": library_id,
                "library_name": lib["name"],
                "removed": removed,
                "remaining_count": remaining_count,
            }

            db.execute(
                """
                INSERT OR IGNORE INTO media_jobs
                    (provider, action, vodum_user_id, server_id, library_id, payload_json, dedupe_key)
                VALUES
                    ('plex', ?, ?, ?, ?, ?, ?)
                """,
                (action, user_id, lib["server_id"], job_library_id, json.dumps(payload), dedupe_key),
            )


            # Activer + queue la tâche apply_plex_access_updates
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
                # pas bloquant si enqueue échoue, le scheduler le prendra plus tard
                pass

        elif server["type"] == "jellyfin":
            # --------------------------------------------------
            # Jellyfin : on fait un job "SYNC" (source de vérité = DB)
            # -> 1 seul job par user+server, réarmé à chaque toggle
            # --------------------------------------------------

            action = "sync"
            job_library_id = None

            # Dedupe par user+server (pas par lib)
            dedupe_key = f"jellyfin:sync:server={lib['server_id']}:user={user_id}"

            payload = {
                "reason": "library_toggle",
                "toggled_library_id": library_id,
                "toggled_library_name": lib["name"],
                "removed": removed,
            }

            # IMPORTANT:
            # - tables.sql: dedupe_key n'est pas UNIQUE => pas de ON CONFLICT possible
            # - on réarme le job en supprimant l'existant (processed ou non), puis insert
            db.execute(
                "DELETE FROM media_jobs WHERE dedupe_key = ?",
                (dedupe_key,),
            )

            # Laisse SQLite appliquer les DEFAULT (processed=0, success=0, attempts=0)
            db.execute(
                """
                INSERT INTO media_jobs
                    (provider, action, vodum_user_id, server_id, library_id, payload_json, dedupe_key)
                VALUES
                    ('jellyfin', ?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    user_id,
                    lib["server_id"],
                    job_library_id,
                    json.dumps(payload, ensure_ascii=False),
                    dedupe_key,
                ),
            )

            # Activer + queue la tâche Jellyfin
            db.execute(
                """
                UPDATE tasks
                SET enabled = 1, status = 'queued'
                WHERE name = 'apply_jellyfin_access_updates'
                """
            )

            try:
                row = db.query_one("SELECT id FROM tasks WHERE name='apply_jellyfin_access_updates'")
                if row:
                    enqueue_task(row["id"])
            except Exception:
                pass




        return redirect(url_for("user_detail", user_id=user_id))





    # -----------------------------
    # SERVEURS & BIBLIO
    # -----------------------------


