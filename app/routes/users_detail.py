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
from .users_list import get_merge_suggestions
from api.subscriptions import update_user_expiration
from notifications_utils import parse_notifications_order


task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

def register(app):
    @app.route("/users/<int:user_id>", methods=["GET", "POST"])
    def user_detail(user_id):
        db = get_db()
        sent_emails = []
        sent_discord = []


        # --------------------------------------------------
        # Charger l’utilisateur (VODUM)
        # --------------------------------------------------
        user = db.query_one(
            "SELECT * FROM vodum_users WHERE id = ?",
            (user_id,),
        )

        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        # on convertit en dict pour éviter les surprises sqlite3.Row
        user = dict(user)

        # --------------------------------------------------
        # Settings (needed for per-user notification override)
        # --------------------------------------------------
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        try:
            user_notifications_can_override = int(settings.get("user_notifications_can_override") or 0) == 1
        except Exception:
            user_notifications_can_override = False


        # --------------------------------------------------
        # Types de serveurs réellement liés à l'utilisateur
        # (basé sur media_users + servers)
        # --------------------------------------------------
        allowed_types = [
            row["type"]
            for row in db.query(
                """
                SELECT DISTINCT s.type
                FROM servers s
                JOIN media_users mu ON mu.server_id = s.id
                WHERE mu.vodum_user_id = ?
                """,
                (user_id,),
            )
            if row["type"]
        ]

        # --------------------------------------------------
        # Tabs (User detail)
        # --------------------------------------------------
        tab = (request.args.get("tab") or "general").strip().lower()
        if tab not in ("general", "monitoring", "access", "notifications", "media"):
            tab = "general"

        mview = (request.args.get("view") or "profile").strip().lower()
        if mview not in ("profile", "history", "ip"):
            mview = "profile"

        # --------------------------------------------------
        # Monitoring: on a besoin d'un media_users.id pour ouvrir la page monitoring/user/<id>
        # (on prend le premier media_user lié au vodum_user)
        # --------------------------------------------------
        monitoring_mu = db.query_one(
            "SELECT id FROM media_users WHERE vodum_user_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        )
        monitoring_mu_id = int(monitoring_mu["id"]) if (monitoring_mu and monitoring_mu["id"] is not None) else None



        # ==================================================
        # POST → Mise à jour utilisateur + options + jobs plex
        # ==================================================
        if request.method == "POST":
            form = request.form

            firstname       = form.get("firstname") or user.get("firstname")
            lastname        = form.get("lastname") or user.get("lastname")
            second_email    = form.get("second_email") or user.get("second_email")
            expiration_date = form.get("expiration_date") or user.get("expiration_date")
            renewal_date    = form.get("renewal_date") or user.get("renewal_date")
            renewal_method  = form.get("renewal_method") or user.get("renewal_method")
            notes           = form.get("notes") if "notes" in form else user.get("notes")

            discord_user_id = (form.get("discord_user_id") or "").strip() or None
            discord_name = (form.get("discord_name") or "").strip() or None

            # Optional per-user stream override (NULL if empty; 0 allowed)
            raw_override = form.get("max_streams_override")
            max_streams_override = None
            if raw_override is not None:
                raw_override = raw_override.strip()
                if raw_override != "":
                    try:
                        max_streams_override = int(raw_override)
                    except Exception:
                        max_streams_override = None


            # --------------------------------------------------
            # Per-user notification order override (optional)
            # - Only allowed if enabled globally in settings
            # --------------------------------------------------
            notifications_order_override = None
            if user_notifications_can_override:
                use_global = (form.get("use_global_notifications_order") == "1")
                if not use_global:
                    raw = (form.get("user_notifications_order") or "").strip()
                    if raw:
                        notifications_order_override = ",".join(parse_notifications_order(raw))
                    else:
                        notifications_order_override = None

            # --- MAJ infos Vodum ---
            db.execute(
                """
                UPDATE vodum_users
                SET firstname = ?, lastname = ?, second_email = ?,
                    renewal_date = ?, renewal_method = ?, notes = ?,
                    max_streams_override = ?,
                    discord_user_id = ?, discord_name = ?, notifications_order_override = ?
                WHERE id = ?
                """,
                (
                    firstname, lastname, second_email,
                    renewal_date, renewal_method, notes,
                    max_streams_override,
                    discord_user_id, discord_name, notifications_order_override,
                    user_id,
                ),
            )

            # Gestion expiration (vodum_users.expiration_date est contractuel)
            if expiration_date != user.get("expiration_date"):
                update_user_expiration(
                    user_id,
                    expiration_date,
                    reason="ui_manual",
                )

            # ------------------------------------------------------------------
            # Helper pour répliquer les flags Plex sur serveurs même owner
            # ------------------------------------------------------------------
            def replicate_plex_flags_same_owner(db, vodum_user_id: int, changed_mu_id: int, plex_share_new: dict):
                """
                Réplique allowSync/allowCameraUpload/allowChannels + filtres sur tous les serveurs Plex
                qui partagent le même owner (approché par même servers.token).
                """
                # serveur lié à ce media_user
                row = db.query_one("SELECT server_id FROM media_users WHERE id = ?", (changed_mu_id,))
                if not row:
                    return
                changed_server_id = int(row["server_id"])

                # token du serveur => proxy owner
                srv = db.query_one("SELECT token FROM servers WHERE id = ?", (changed_server_id,))
                if not srv:
                    return
                srv = dict(srv)
                owner_token = srv.get("token")
                if not owner_token:
                    return

                # tous les serveurs plex du même owner
                owner_servers = db.query(
                    "SELECT id FROM servers WHERE type='plex' AND token = ?",
                    (owner_token,),
                )
                owner_server_ids = [int(s["id"]) for s in owner_servers]
                if not owner_server_ids:
                    return

                placeholders = ",".join(["?"] * len(owner_server_ids))

                rows = db.query(
                    f"""
                    SELECT mu.id, mu.details_json
                    FROM media_users mu
                    JOIN servers s ON s.id = mu.server_id
                    WHERE mu.vodum_user_id = ?
                      AND s.type = 'plex'
                      AND mu.type = 'plex'
                      AND mu.server_id IN ({placeholders})
                    """,
                    (vodum_user_id, *owner_server_ids),
                )

                for r in rows:
                    mu_id2 = int(r["id"])
                    try:
                        details2 = json.loads(r["details_json"] or "{}")
                    except Exception:
                        details2 = {}

                    if not isinstance(details2, dict):
                        details2 = {}

                    plex_share2 = details2.get("plex_share", {})
                    if not isinstance(plex_share2, dict):
                        plex_share2 = {}

                    # réplique les champs qui doivent être identiques pour un même owner
                    for k in ("allowSync", "allowCameraUpload", "allowChannels", "filterMovies", "filterTelevision", "filterMusic"):
                        if k in plex_share_new:
                            plex_share2[k] = plex_share_new[k]

                    details2["plex_share"] = plex_share2

                    db.execute(
                        "UPDATE media_users SET details_json = ? WHERE id = ?",
                        (json.dumps(details2, ensure_ascii=False), mu_id2),
                    )

            # -----------------------------------------------
            # Sauvegarde des options Plex en JSON (details_json)
            # -> 1 details_json par media_user (donc par serveur)
            # -----------------------------------------------
            plex_media = db.query(
                """
                SELECT mu.id, mu.details_json
                FROM media_users mu
                JOIN servers s ON s.id = mu.server_id
                WHERE mu.vodum_user_id = ?
                  AND s.type = 'plex'
                  AND mu.type = 'plex'
                """,
                (user_id,),
            )

            truthy = {"1", "true", "on", "yes"}

            for mu in plex_media:
                mu_id = int(mu["id"])

                # Charge le JSON existant
                try:
                    details = json.loads(mu["details_json"] or "{}")
                except Exception:
                    details = {}

                if not isinstance(details, dict):
                    details = {}

                plex_share = details.get("plex_share", {})
                if not isinstance(plex_share, dict):
                    plex_share = {}

                # allowSync
                vals = form.getlist(f"allow_sync_{mu_id}")
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_sync getlist={vals}")
                v = vals[-1] if vals else None
                if v is not None:
                    plex_share["allowSync"] = 1 if str(v).strip().lower() in truthy else 0
                else:
                    plex_share["allowSync"] = int(plex_share.get("allowSync", 0) or 0)

                # allowCameraUpload
                vals = form.getlist(f"allow_camera_upload_{mu_id}")
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_camera_upload getlist={vals}")
                v = vals[-1] if vals else None
                if v is not None:
                    plex_share["allowCameraUpload"] = 1 if str(v).strip().lower() in truthy else 0
                else:
                    plex_share["allowCameraUpload"] = int(plex_share.get("allowCameraUpload", 0) or 0)

                # allowChannels
                vals = form.getlist(f"allow_channels_{mu_id}")
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_channels getlist={vals}")
                v = vals[-1] if vals else None
                if v is not None:
                    plex_share["allowChannels"] = 1 if str(v).strip().lower() in truthy else 0
                else:
                    plex_share["allowChannels"] = int(plex_share.get("allowChannels", 0) or 0)

                plex_share["filterMovies"] = (form.get(f"filter_movies_{mu_id}") or "").strip()
                plex_share["filterTelevision"] = (form.get(f"filter_television_{mu_id}") or "").strip()
                plex_share["filterMusic"] = (form.get(f"filter_music_{mu_id}") or "").strip()

                details["plex_share"] = plex_share

                db.execute(
                    "UPDATE media_users SET details_json = ? WHERE id = ?",
                    (json.dumps(details, ensure_ascii=False), mu_id),
                )

                # Réplication même owner
                replicate_plex_flags_same_owner(
                    db,
                    vodum_user_id=user_id,
                    changed_mu_id=mu_id,
                    plex_share_new=plex_share,
                )

            # -----------------------------------------------
            # SYNC Plex : pour chaque serveur plex lié à cet user,
            # créer un job compatible apply_plex_access_updates (media_jobs)
            # -----------------------------------------------
            if "plex" in allowed_types:
                plex_media_for_jobs = db.query(
                    """
                    SELECT mu.id, mu.server_id
                    FROM media_users mu
                    JOIN servers s ON s.id = mu.server_id
                    WHERE mu.vodum_user_id = ?
                      AND s.type = 'plex'
                      AND mu.type = 'plex'
                    """,
                    (user_id,),
                )

                # On déduplique par serveur : un sync par serveur suffit (il applique toutes les libs de l'user)
                plex_server_ids = sorted({int(mu["server_id"]) for mu in plex_media_for_jobs if mu["server_id"] is not None})

                for server_id in plex_server_ids:
                    dedupe_key = f"plex:sync:server={server_id}:vodum_user={user_id}:user_detail_save"

                    payload = {
                        "reason": "user_detail_save",
                        "updated_options": True,
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
                        (user_id, server_id, json.dumps(payload, ensure_ascii=False), dedupe_key),
                    )

                # Activer + queue apply_plex_access_updates
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
                    # pas bloquant si enqueue échoue
                    pass

            flash("user_saved", "success")
            return redirect(url_for("user_detail", user_id=user_id))

        # ==================================================
        # GET → Chargement infos complètes
        # ==================================================

        servers = db.query(
            """
            SELECT
                s.*,
                s.id AS server_id,

                mu.id AS media_user_id,
                mu.external_user_id,
                mu.username AS media_username,
                mu.email AS media_email,
                mu.avatar AS media_avatar,
                mu.type AS media_type,
                mu.role AS media_role,
                mu.joined_at,
                mu.accepted_at,
                mu.details_json,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM media_user_libraries mul
                        WHERE mul.media_user_id = mu.id
                        LIMIT 1
                    ) THEN 1
                    ELSE 0
                END AS has_access
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.vodum_user_id = ?
            ORDER BY s.type, s.name
            """,
            (user_id,),
        )

        enriched = []
        for row in servers:
            r = dict(row)

            # defaults pour le template
            r["allow_sync"] = 0
            r["allow_camera_upload"] = 0
            r["allow_channels"] = 0
            r["filter_movies"] = ""
            r["filter_television"] = ""
            r["filter_music"] = ""

            try:
                details = json.loads(r.get("details_json") or "{}")
            except Exception:
                details = {}

            if not isinstance(details, dict):
                details = {}

            # Plex
            if r.get("media_type") == "plex":
                plex_share = details.get("plex_share", {})
                if not isinstance(plex_share, dict):
                    plex_share = {}

                r["allow_sync"] = 1 if plex_share.get("allowSync") else 0
                r["allow_camera_upload"] = 1 if plex_share.get("allowCameraUpload") else 0
                r["allow_channels"] = 1 if plex_share.get("allowChannels") else 0
                r["filter_movies"] = plex_share.get("filterMovies") or ""
                r["filter_television"] = plex_share.get("filterTelevision") or ""
                r["filter_music"] = plex_share.get("filterMusic") or ""

            r["_details_obj"] = details
            enriched.append(r)

        servers = enriched

        libraries = db.query(
            """
            SELECT
                l.*,
                s.name AS server_name,
                CASE
                    WHEN mul.media_user_id IS NOT NULL THEN 1
                    ELSE 0
                END AS has_access
            FROM libraries l
            JOIN servers s ON s.id = l.server_id
            LEFT JOIN media_user_libraries mul
                   ON mul.library_id = l.id
                  AND mul.media_user_id IN (
                        SELECT id
                        FROM media_users
                        WHERE vodum_user_id = ?
                   )
            ORDER BY s.name, l.name
            """,
            (user_id,),
        )



        merge_suggestions = get_merge_suggestions(db, user_id, limit=None)

        # --------------------------------------------------
        # merged_usernames = tous les usernames "liés" (media_users)
        # SAUF le username principal (vodum_users.username)
        # --------------------------------------------------
        main_username = (user.get("username") or "").strip().lower()

        merged_usernames_set = set()

        rows = db.query(
            """
            SELECT DISTINCT username
            FROM media_users
            WHERE vodum_user_id = ?
              AND username IS NOT NULL
              AND TRIM(username) <> ''
            """,
            (user_id,),
        )

        for r in rows:
            uname = str(r["username"]).strip()
            if uname and uname.lower() != main_username:
                merged_usernames_set.add(uname)

        merged_usernames = sorted(merged_usernames_set, key=lambda x: x.lower())

        # ----------------------------
        # Notification history paging
        # ----------------------------
        def _safe_int(v, default):
            try:
                return int(v)
            except Exception:
                return default

        per_page = 10

        email_page = max(1, _safe_int(request.args.get("email_page"), 1))
        discord_page = max(1, _safe_int(request.args.get("discord_page"), 1))

        email_total = db.query_one(
            "SELECT COUNT(*) AS c FROM sent_emails WHERE user_id = ?",
            (user_id,),
        )["c"] or 0

        discord_total = db.query_one(
            "SELECT COUNT(*) AS c FROM sent_discord WHERE user_id = ?",
            (user_id,),
        )["c"] or 0

        email_pages = max(1, math.ceil(email_total / per_page)) if email_total else 1
        discord_pages = max(1, math.ceil(discord_total / per_page)) if discord_total else 1

        email_page = min(email_page, email_pages)
        discord_page = min(discord_page, discord_pages)

        email_offset = (email_page - 1) * per_page
        discord_offset = (discord_page - 1) * per_page

        sent_emails = db.query(
            """
            SELECT *
            FROM sent_emails
            WHERE user_id = ?
            ORDER BY sent_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, email_offset),
        )

        sent_discord = db.query(
            """
            SELECT
              template_type,
              expiration_date,
              datetime(sent_at, 'unixepoch', 'localtime') AS sent_at
            FROM sent_discord
            WHERE user_id = ?
            ORDER BY sent_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, discord_offset),
        )



        return render_template(
            "users/user_detail.html",
            user=user,
            servers=servers,
            libraries=libraries,
            sent_emails=sent_emails,
            sent_discord=sent_discord,
            allowed_types=allowed_types,
            merge_suggestions=merge_suggestions,
            user_servers=servers,
            merged_usernames=merged_usernames,
            email_page=email_page,
            email_pages=email_pages,
            email_total=email_total,

            discord_page=discord_page,
            discord_pages=discord_pages,
            discord_total=discord_total,

            per_page=per_page,


            # tabs
            tab=tab,
            mview=mview,
            monitoring_mu_id=monitoring_mu_id,
            settings=settings,
            user_notifications_can_override=user_notifications_can_override,
        )





