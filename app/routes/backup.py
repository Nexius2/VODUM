# Auto-split from app.py (keep URLs/endpoints intact)
from datetime import datetime
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename

from logging_utils import get_logger
from tasks_engine import enable_and_run_task_by_name
from core.i18n import get_translator
from core.backup import list_backups
from core.app_paths import imports_dir as get_imports_dir
from db_manager import open_sqlite_connection

from web.helpers import get_db, get_backup_cfg

settings_logger = get_logger("settings")

BACKUP_SETTINGS_COLUMNS = """
    backup_retention_days,
    backup_retention_count,
    data_retention_years
"""



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
        settings_logger.error("Unable to determine SQLite database size", exc_info=True)
        return None

def register(app):

    def _task_diagnostic(db, task_name: str) -> dict:
        row = db.query_one(
            """
            SELECT status, last_run, last_error, last_attempt_at
            FROM tasks
            WHERE name = ?
            """,
            (task_name,),
        )
        return dict(row) if row else {
            "status": "unknown",
            "last_run": None,
            "last_error": None,
            "last_attempt_at": None,
        }

    def _resolve_backup_path(selected_name: str) -> Path:
        """
        Ne permet de restaurer qu'un fichier présent dans BACKUP_DIR.
        Empêche toute traversée de chemin.
        """
        base_dir = Path(app.config["BACKUP_DIR"]).resolve()

        selected_name = (selected_name or "").strip()
        if not selected_name:
            raise ValueError("Empty backup name")

        # force un nom de fichier simple
        safe_name = secure_filename(selected_name)
        if not safe_name or safe_name != selected_name:
            raise ValueError("Invalid backup name")

        backup_path = (base_dir / safe_name).resolve()

        # vérifie que le chemin final reste bien dans BACKUP_DIR
        try:
            backup_path.relative_to(base_dir)
        except Exception:
            raise ValueError("Backup path escapes backup directory")

        if not backup_path.is_file():
            raise FileNotFoundError(str(backup_path))

        return backup_path




    def _looks_like_tautulli_db(path: str) -> tuple[bool, str]:
        """
        Returns (ok, details). details contains tables count or the exception message.
        """
        try:
            # Ouvre en lecture seule (évite toute création implicite)
            with open_sqlite_connection(path, read_only=True) as conn:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {r[0] for r in cur.fetchall()}

            required = {"users", "session_history", "session_history_metadata", "library_sections"}
            missing = sorted(list(required - tables))
            if missing:
                return False, f"Missing required tables: {', '.join(missing)} (found={len(tables)})"
            return True, f"OK (found_tables={len(tables)})"

        except Exception as e:
            return False, f"{type(e).__name__}: {e}"


    def _render_backup_page():
        backup_cfg = get_backup_cfg()
        db = get_db()

        settings = db.query_one(f"SELECT {BACKUP_SETTINGS_COLUMNS} FROM settings LIMIT 1")
        plex_servers = db.query("SELECT id, name FROM servers WHERE type='plex' ORDER BY name ASC")
        db_size_bytes = get_sqlite_db_size_bytes(app.config["DATABASE"])
        backups = list_backups(backup_cfg)
        backup_diagnostic = _task_diagnostic(db, "auto_backup")
        integrity_diagnostic = _task_diagnostic(db, "db_integrity_check")

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
            backup_diagnostic=backup_diagnostic,
            integrity_diagnostic=integrity_diagnostic,
        )

    @app.route("/backup/download/<path:filename>", methods=["GET"])
    def download_backup(filename):
        try:
            backup_path = _resolve_backup_path(filename)

            return send_file(
                backup_path,
                as_attachment=True,
                download_name=backup_path.name,
                mimetype="application/octet-stream",
                max_age=0,
            )

        except Exception as e:
            settings_logger.warning("Backup download failed for %r: %s", filename, e, exc_info=True)
            flash(f"Download failed: {e}", "error")
            return redirect(url_for("backup_page"))



    @app.route("/backup/delete", methods=["POST"])
    def delete_backup():
        try:
            data = request.get_json(silent=True) or {}
            filename = data.get("filename")

            if not filename:
                return {"success": False, "error": "missing filename"}, 400

            if not filename.endswith((".zip", ".sqlite", ".db")):
                return {"success": False, "error": "invalid backup"}, 400

            backup_path = _resolve_backup_path(filename)

            if backup_path.exists():
                backup_path.unlink()

            return {"success": True}

        except Exception as e:
            settings_logger.error("Backup deletion failed", exc_info=True)
            return {"success": False, "error": str(e)}, 500

    @app.route("/backup/action", methods=["POST"])
    def backup_action():
        t = get_translator()
        db = get_db()

        action = request.form.get("action")

        # ───────────────────────────────
        # Backup manuel
        # ───────────────────────────────
        if action == "create":
            try:
                queued = enable_and_run_task_by_name("auto_backup")
                if queued:
                    flash("Manual backup queued.", "success")
                    return redirect(url_for("backup_page", refresh_backups="1"))
                else:
                    flash("Manual backup could not be queued.", "error")
                    return redirect(url_for("backup_page"))
            except Exception as e:
                settings_logger.exception("Manual backup enqueue failed")
                flash(t("backup_create_error").format(error=str(e)), "error")
                return redirect(url_for("backup_page"))

        # ───────────────────────────────
        # Restauration d'un backup
        # ───────────────────────────────
        elif action == "restore":
            selected = request.form.get("selected_backup")
            imports_dir = get_imports_dir()
            imports_dir.mkdir(parents=True, exist_ok=True)
            request_path_file = imports_dir / "restore_request_path.txt"

            # 1) Restore depuis un backup existant
            if selected:
                try:
                    backup_path = _resolve_backup_path(selected)
                except FileNotFoundError:
                    flash(t("backup_not_found"), "error")
                    return redirect(url_for("backup_page"))
                except Exception as e:
                    settings_logger.exception("Backup restore path validation failed")
                    flash(t("backup_restore_error").format(error=str(e)), "error")
                    return redirect(url_for("backup_page"))

                try:
                    request_path_file.write_text(str(backup_path), encoding="utf-8")
                    queued = enable_and_run_task_by_name("restore_backup")
                    if not queued:
                        flash("Restore could not be queued.", "error")
                        return redirect(url_for("backup_page"))

                    flash("Restore queued. The container will restart automatically after completion.", "success")
                    return redirect(url_for("backup_page"))
                except Exception as e:
                    settings_logger.exception("Existing backup restore enqueue failed")
                    flash(t("backup_restore_error").format(error=str(e)), "error")
                    return redirect(url_for("backup_page"))

            # 2) Restore par upload
            else:
                file = request.files.get("backup_file")

                if not file or file.filename == "":
                    flash(t("backup_no_file"), "error")
                else:
                    original_name = secure_filename(file.filename or "")
                    original_suffix = Path(original_name).suffix.lower()

                    if original_suffix not in {".zip", ".sqlite", ".db"}:
                        flash("Unsupported backup format. Please upload a .zip, .sqlite or .db backup.", "error")
                        return redirect(url_for("backup_page"))

                    temp_path = imports_dir / f"restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{original_suffix}"

                    try:
                        file.save(temp_path)
                        request_path_file.write_text(str(temp_path), encoding="utf-8")

                        queued = enable_and_run_task_by_name("restore_backup")
                        if not queued:
                            flash("Restore could not be queued.", "error")
                            return redirect(url_for("backup_page"))

                        flash("Restore queued. The container will restart automatically after completion.", "success")
                        return redirect(url_for("backup_page"))
                    except Exception as e:
                        settings_logger.exception("Uploaded backup restore enqueue failed")
                        flash(t("backup_restore_error").format(error=str(e)), "error")
                        return redirect(url_for("backup_page"))

        # ───────────────────────────────
        # Sauvegarde des paramètres (rétention)
        # ───────────────────────────────
        elif action == "save_settings":
            try:
                days = int(request.form.get("backup_retention_days", "30"))
                count = int(request.form.get("backup_retention_count", "10"))
                years = int(request.form.get("data_retention_years", "0"))

                if days < 1:
                    days = 30
                if count < 1:
                    count = 10
                if years < 0:
                    years = 0

                db.execute(
                    "UPDATE settings SET backup_retention_days = ?, backup_retention_count = ?, data_retention_years = ?",
                    (days, count, years),
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
                    imports_dir = get_imports_dir()
                    imports_dir.mkdir(parents=True, exist_ok=True)

                    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    final_path = imports_dir / f"tautulli_{ts}.db"

                    tmp_path = imports_dir / f".tautulli_{ts}.uploading"
                    try:
                        file.save(str(tmp_path))
                    except Exception as e:
                        log.error(f"[TAUTULLI UI] file.save failed to {tmp_path}: {e}", exc_info=True)
                        flash(f"Upload failed: {e}", "error")
                        return _render_backup_page()

                    size = -1
                    try:
                        size = tmp_path.stat().st_size
                    except Exception:
                        log.warning(f"[TAUTULLI UI] unable to read upload size for {tmp_path}", exc_info=True)

                    log.info(f"[TAUTULLI UI] uploaded tmp file={tmp_path} size={size} bytes")

                    if size < 4096:
                        bad = imports_dir / f"tautulli_{ts}.too_small"
                        try:
                            tmp_path.replace(bad)
                        except Exception:
                            log.warning(f"[TAUTULLI UI] unable to preserve too-small upload {tmp_path}", exc_info=True)
                        flash(
                            f"Upload looks too small ({size} bytes). File kept as {bad.name} for inspection.",
                            "error",
                        )
                    else:
                        try:
                            tmp_path.replace(final_path)
                        except Exception as e:
                            log.error(f"[TAUTULLI UI] atomic move failed: {tmp_path} -> {final_path}: {e}", exc_info=True)
                            flash(f"Cannot finalize upload file: {e}", "error")
                        else:
                            ok, details = _looks_like_tautulli_db(str(final_path))
                            log.info(f"[TAUTULLI UI] validate {final_path}: ok={ok} details={details}")

                            if not ok:
                                invalid_path = imports_dir / f"tautulli_{ts}.invalid.db"
                                try:
                                    final_path.replace(invalid_path)
                                except Exception:
                                    log.warning(f"[TAUTULLI UI] unable to preserve invalid upload {final_path}", exc_info=True)
                                    invalid_path = final_path

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
                                      keep_all_users,
                                      keep_all_libraries, import_only_available_libraries, target_server_id,
                                      status
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, 'queued')
                                    """,
                                    (
                                        0,
                                        str(final_path),
                                        int(keep_all_users),
                                        int(keep_all_libraries),
                                        int(import_only_available_libraries),
                                        int(target_server_id),
                                    ),
                                )

                                job_id = None
                                try:
                                    job_id = int(cur.lastrowid)
                                except Exception:
                                    log.warning("[TAUTULLI UI] unable to read inserted job id", exc_info=True)

                                log.info(
                                    f"[TAUTULLI UI] job enqueued (job_id={job_id}) file={final_path} "
                                    f"keep_all_users={keep_all_users} "
                                    f"keep_all_libraries={keep_all_libraries} "
                                    f"import_only_available_libraries={import_only_available_libraries} "
                                    f"target_server_id={target_server_id}"
                                )

                                flash(
                                    "Tautulli database uploaded. Import can take a long time — please be patient.",
                                    "info",
                                )

                                enable_and_run_task_by_name("import_tautulli")

            except Exception as e:
                get_logger("backup").error("Unable to start Tautulli import", exc_info=True)
                flash(f"Error while starting import: {e}", "error")

        return redirect(url_for("backup_page"))

    @app.route("/api/backup/list", methods=["GET"])
    def api_backup_list():
        backup_cfg = get_backup_cfg()
        backups = list_backups(backup_cfg)
        return {"backups": backups}

    @app.route("/backup", methods=["GET"])
    def backup_page():
        return _render_backup_page()
