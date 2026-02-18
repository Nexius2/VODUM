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



def get_sqlite_db_size_bytes(db_path: str) -> int | None:
    """Retourne la taille disque de la DB SQLite (inclut -wal/-shm si présents)."""
    try:
        p = Path(db_path)
        if not p.exists():
            return None
        size = p.stat().st_size
        wal = p.with_suffix(p.suffix + '-wal')
        shm = p.with_suffix(p.suffix + '-shm')
        if wal.exists():
            size += wal.stat().st_size
        if shm.exists():
            size += shm.stat().st_size
        return size
    except Exception:
        return None

def register(app):

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


    @app.route("/backup", methods=["GET", "POST"])
    def backup_page():
        backup_cfg = get_backup_cfg()
        t = get_translator()
        db = get_db()

        # Charger les réglages (dont la rétention)
        settings = db.query_one("SELECT * FROM settings LIMIT 1")

        plex_servers = db.query("SELECT id, name FROM servers WHERE type='plex' ORDER BY name ASC")


        db_size_bytes = get_sqlite_db_size_bytes(app.config["DATABASE"])
        backups = list_backups(backup_cfg)

        if request.method == "POST":
            action = request.form.get("action")

            # ───────────────────────────────
            # Backup manuel
            # ───────────────────────────────
            if action == "create":
                try:
                    name = create_backup_file(get_db, backup_cfg)
                    flash(t("backup_created").format(name=name), "success")
                except Exception as e:
                    flash(t("backup_create_error").format(error=str(e)), "error")

            # ───────────────────────────────
            # Restauration d'un backup
            # ───────────────────────────────
            elif action == "restore":
                selected = request.form.get("selected_backup")

                # 1) Restore depuis un backup existant
                if selected:
                    backup_path = Path(app.config["BACKUP_DIR"]) / selected

                    if not backup_path.exists():
                        flash(t("backup_not_found"), "error")
                        return redirect(url_for("backup_page"))

                    try:
                        safe_restore(backup_path)
                        flash(t("backup_restore_success_restart"), "success")
                        return redirect(url_for("backup_page"))  # <- IMPORTANT
                    except Exception as e:
                        flash(t("backup_restore_error").format(error=str(e)), "error")
                        return redirect(url_for("backup_page"))





                # 2) Restore par upload
                else:
                    file = request.files.get("backup_file")

                    if not file or file.filename == "":
                        flash(t("backup_no_file"), "error")
                    else:
                        temp_dir = Path("/tmp")
                        temp_dir.mkdir(exist_ok=True)
                        temp_path = temp_dir / f"restore-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sqlite"

                        file.save(temp_path)

                        try:
                            safe_restore(temp_path)  # ✅ même méthode que “restore depuis backup existant”
                            flash(t("backup_restore_success_restart"), "success")
                            return redirect(url_for("backup_page"))
                        except Exception as e:
                            flash(t("backup_restore_error").format(error=str(e)), "error")
                            return redirect(url_for("backup_page"))
                        finally:
                            if temp_path.exists():
                                temp_path.unlink(missing_ok=True)

            # ───────────────────────────────
            # Sauvegarde des paramètres (rétention)
            # ───────────────────────────────
            elif action == "save_settings":
                try:
                    days = int(request.form.get("backup_retention_days", "30"))
                    years = int(request.form.get("data_retention_years", "0"))

                    # Safety: keep sane values
                    if days < 1:
                        days = 30
                    if years < 0:
                        years = 0

                    db.execute(
                        "UPDATE settings SET backup_retention_days = ?, data_retention_years = ?",
                        (days, years),
                    )
                    flash(t("backup_settings_saved"), "success")
                except Exception as e:
                    flash(t("backup_settings_error").format(error=str(e)), "error")



            # ───────────────────────────────
            # Import Tautulli
            # ───────────────────────────────
            elif action == "tautulli_import":
                try:
                    keep_all_users = 1 if request.form.get("tautulli_keep_all_users") == "1" else 0
                    keep_all_servers = 0  # legacy


                    libraries_mode = (request.form.get("tautulli_libraries_mode") or "only_existing").strip()
                    import_only_available_libraries = 1 if libraries_mode == "only_existing" else 0
                    keep_all_libraries = 1 if libraries_mode == "keep_all" else 0

                    target_server_id_raw = (request.form.get("tautulli_target_server_id") or "").strip()
                    target_server_id = int(target_server_id_raw) if target_server_id_raw.isdigit() else 0


                    log = get_logger("backup")

                    file = request.files.get("tautulli_db")
                    if not file or file.filename == "":
                        flash("No file provided.", "error")
                    else:
                        imports_dir = Path("/appdata/imports")
                        imports_dir.mkdir(parents=True, exist_ok=True)

                        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                        final_path = imports_dir / f"tautulli_{ts}.db"

                        # Save to a temporary file first, then atomic move.
                        tmp_path = imports_dir / f".tautulli_{ts}.uploading"
                        try:
                            file.save(str(tmp_path))  # str() pour éviter tout souci Path/Werkzeug
                        except Exception as e:
                            log.error(f"[TAUTULLI UI] file.save failed to {tmp_path}: {e}", exc_info=True)
                            flash(f"Upload failed: {e}", "error")
                            backups = list_backups(backup_cfg)
                            tautulli_job = db.query_one("""
                                SELECT id, status, created_at, started_at, finished_at, stats_json, last_error
                                FROM tautulli_import_jobs
                                ORDER BY id DESC
                                LIMIT 1
                            """)
                            return render_template(
                                "backup/backup.html",
                                backups=backups,
                                settings=settings,
                                db_size_bytes=db_size_bytes,
                                active_page="backup",
                                plex_servers=plex_servers,
                                tautulli_job=tautulli_job,
                            )

                        # Check size (detect empty/truncated uploads)
                        size = -1
                        try:
                            size = tmp_path.stat().st_size
                        except Exception:
                            pass

                        log.info(f"[TAUTULLI UI] uploaded tmp file={tmp_path} size={size} bytes")

                        if size < 4096:
                            # Keep the file for inspection, do not delete.
                            bad = imports_dir / f"tautulli_{ts}.too_small"
                            try:
                                tmp_path.replace(bad)
                            except Exception:
                                pass
                            flash(
                                f"Upload looks too small ({size} bytes). File kept as {bad.name} for inspection.",
                                "error",
                            )
                        else:
                            # Atomic move into final name
                            try:
                                tmp_path.replace(final_path)
                            except Exception as e:
                                log.error(f"[TAUTULLI UI] atomic move failed: {tmp_path} -> {final_path}: {e}", exc_info=True)
                                flash(f"Cannot finalize upload file: {e}", "error")
                            else:
                                ok, details = _looks_like_tautulli_db(str(final_path))
                                log.info(f"[TAUTULLI UI] validate {final_path}: ok={ok} details={details}")

                                if not ok:
                                    # IMPORTANT: do NOT delete -> keep file for debugging
                                    invalid_path = imports_dir / f"tautulli_{ts}.invalid.db"
                                    try:
                                        final_path.replace(invalid_path)
                                    except Exception:
                                        invalid_path = final_path  # fallback

                                    flash(
                                        f"This file does not look like a valid Tautulli DB. "
                                        f"Reason: {details}. File kept as {invalid_path.name}.",
                                        "error",
                                    )
                                else:
                                    cur = db.execute(
                                        """
                                        INSERT INTO tautulli_import_jobs(
                                          server_id, file_path,
                                          keep_all_servers, keep_all_users,
                                          keep_all_libraries, import_only_available_libraries, target_server_id,
                                          status
                                        )
                                        VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')

                                        """,
                                        (0, str(final_path), 0, int(keep_all_users), int(keep_all_libraries), int(import_only_available_libraries), int(target_server_id)),
                                    )

                                    job_id = None
                                    try:
                                        job_id = int(cur.lastrowid)
                                    except Exception:
                                        pass

                                    log.info(
                                        f"[TAUTULLI UI] job enqueued (job_id={job_id}) file={final_path} "
                                        f"keep_all_servers={keep_all_servers} keep_all_users={keep_all_users}"
                                    )

                                    flash(
                                        "Tautulli database uploaded. Import can take a long time — please be patient.",
                                        "info",
                                    )

                                    # Trigger task now
                                    run_task_by_name("import_tautulli")

                except Exception as e:
                    flash(f"Error while starting import: {e}", "error")




            # Refresh backups list after any POST action
            backups = list_backups(backup_cfg)

        # Dernier job Tautulli (pour afficher l'état sur la page)
        tautulli_job = db.query_one("""
            SELECT id, status, created_at, started_at, finished_at, stats_json, last_error
            FROM tautulli_import_jobs
            ORDER BY id DESC
            LIMIT 1
        """)


        return render_template(
            "backup/backup.html",
            backups=backups,
            settings=settings,
            db_size_bytes=db_size_bytes,
            active_page="backup",
            plex_servers=plex_servers,
            tautulli_job=tautulli_job,
        )



