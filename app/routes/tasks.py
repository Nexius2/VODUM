# Auto-split from app.py (keep URLs/endpoints intact)
import os
import json
import ipaddress

from flask import (
    render_template, request, redirect, url_for, flash, session,
    jsonify, abort,
)

from logging_utils import get_logger
from tasks_engine import (
    enqueue_task,
    set_task_enabled,
    set_tasks_enabled_by_names,
    mark_task_manual_run_requested,
    mark_task_queue_failed,
)
from web.helpers import get_db, table_exists, add_log

task_logger = get_logger("tasks_ui")

def register(app):
    @app.route("/tasks", methods=["GET"])
    def tasks_page():
        db = get_db()

        tasks = []
        if table_exists(db, "tasks"):
            tasks = db.query(
                """
                SELECT *
                FROM tasks
                ORDER BY name
                """
            )

        task_logger.debug(f"Affichage page tasks → {len(tasks)} tâches détectées")

        return render_template(
            "tasks/tasks.html",
            tasks=tasks,
            active_page="tasks",
        )

    @app.route("/tasks/action", methods=["POST"])
    def tasks_action():
        db = get_db()

        if not table_exists(db, "tasks"):
            flash("invalid_task", "error")
            task_logger.error("POST /tasks/action → table tasks absente")
            return redirect(url_for("tasks_page"))

        task_id = request.form.get("task_id", type=int)
        action = (request.form.get("action") or "").strip()

        if not task_id:
            flash("invalid_task", "error")
            task_logger.error("POST /tasks/action → task_id manquant")
            return redirect(url_for("tasks_page"))

        task = db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not task:
            flash("invalid_task", "error")
            task_logger.error(f"POST /tasks/action → task_id introuvable: {task_id}")
            return redirect(url_for("tasks_page"))

        if action == "toggle":
            new_enabled = 0 if int(task["enabled"] or 0) == 1 else 1
            set_task_enabled(task_id, new_enabled)

            if new_enabled == 1:
                task_logger.info(f"Tâche {task_id} → ENABLED (status=idle)")
            else:
                task_logger.info(f"Tâche {task_id} → DISABLED (status=disabled)")

            flash("task_updated", "success")
            return redirect(url_for("tasks_page"))

        if action == "run_now":
            row = db.query_one("SELECT enabled, status, name FROM tasks WHERE id = ?", (task_id,))
            enabled = int(row["enabled"]) if row else 0
            name = row["name"] if row and "name" in row else f"#{task_id}"

            if enabled != 1:
                flash("task_disabled", "error")
                task_logger.warning(f"run_now refusé: tâche {task_id} ({name}) désactivée")
                return redirect(url_for("tasks_page"))

            mark_task_manual_run_requested(task_id)

            try:
                enqueue_task(task_id)
                flash("task_queued", "success")
                task_logger.info(f"Tâche {task_id} ({name}) → run_now → enqueued")
            except Exception as e:
                flash("task_queue_failed", "error")
                task_logger.error(f"run_now erreur pour tâche {task_id} ({name}): {e}", exc_info=True)
                try:
                    mark_task_queue_failed(task_id, str(e))
                except Exception:
                    pass

            return redirect(url_for("tasks_page"))

        task_logger.warning(f"Action inconnue sur /tasks/action : {action} (task_id={task_id})")
        flash("unknown_action", "error")
        return redirect(url_for("tasks_page"))




    # -----------------------------
    # MAILING
    # -----------------------------
    
    def is_smtp_ready(settings) -> bool:
        if not settings:
            return False

        try:
            return bool(
                settings["mailing_enabled"]
                and settings["smtp_host"]
                and settings["smtp_port"]
                and settings["smtp_user"]
                and settings["smtp_pass"]
                and settings["mail_from"]
            )
        except (KeyError, TypeError):
            return False


    
    @app.post("/api/mailing/toggle")
    def api_mailing_toggle():
        db = get_db()

        data = request.get_json(silent=True) or {}
        enabled = 1 if data.get("enabled") else 0

        try:
            # Mettre à jour le flag settings (WRITE)
            db.execute(
                "UPDATE settings SET mailing_enabled = ? WHERE id = 1",
                (enabled,),
            )

            # Activer / désactiver les tâches liées au mailing (WRITE)
            set_tasks_enabled_by_names(
                ["send_expiration_emails", "send_mail_campaigns", "send_comm_campaigns"],
                enabled,
            )

            add_log(
                "info",
                "mailing",
                f"Mailing toggled → {enabled}",
            )

            return {"status": "ok", "enabled": enabled}

        except Exception as e:
            # pas de rollback avec DBManager
            add_log(
                "error",
                "mailing",
                "Failed to toggle mailing",
                {"error": str(e)},
            )
            return {"status": "error", "message": str(e)}, 500








    def json_rows(rows):
        return json.dumps([dict(r) for r in rows], ensure_ascii=False), 200, {"Content-Type": "application/json"}


    @app.route("/backup/tautulli-import/status", methods=["GET"])
    def tautulli_import_status():
        db = get_db()
        job = db.query_one("""
            SELECT id, status, created_at, started_at, finished_at, stats_json, last_error
            FROM tautulli_import_jobs
            ORDER BY id DESC
            LIMIT 1
        """)

        if not job:
            return jsonify({"status": "none"})

        # job est une row sqlite => dict(row) ok dans ton codebase
        j = dict(job)

        return jsonify({
            "status": j.get("status"),
            "id": j.get("id"),
            "created_at": j.get("created_at"),
            "started_at": j.get("started_at"),
            "finished_at": j.get("finished_at"),
            "stats_json": j.get("stats_json"),
            "last_error": j.get("last_error"),
        })



    # -----------------------------
    # AUTH (admin) - guard global
    # -----------------------------
    def _get_auth_settings():
        db = get_db()
        row = db.query_one(
            "SELECT admin_email, admin_password_hash, auth_enabled FROM settings WHERE id = 1"
        )
        return dict(row) if row else {"admin_email": "", "admin_password_hash": None, "auth_enabled": 1}

    def _is_auth_configured(s: dict) -> bool:
        return bool((s.get("admin_password_hash") or "").strip())

    def _is_logged_in() -> bool:
        return session.get("vodum_logged_in") is True

    def _is_private_ip(ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_private or ip.is_loopback
        except Exception:
            return False


    def _get_client_ip() -> str:
        remote = request.remote_addr or ""

        xff = (request.headers.get("X-Forwarded-For") or "").strip()
        if xff and _is_private_ip(remote):
            # XFF peut contenir "client, proxy1, proxy2"
            first = xff.split(",")[0].strip()
            if first:
                return first

        return remote


    def _ip_allowed(remote_ip: str) -> bool:
        # Permet de désactiver le filtrage si besoin 
        if (os.environ.get("VODUM_IP_FILTER") or "1").strip() in ("0", "false", "False", "no", "NO"):
            return True

        # ✅ Valeur par défaut 
        default_allowed = "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

        allowed = (os.environ.get("VODUM_ALLOWED_NETS") or default_allowed).strip()

        try:
            ip = ipaddress.ip_address(remote_ip)
        except Exception:
            return False

        for part in allowed.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                net = ipaddress.ip_network(part, strict=False)
                if ip in net:
                    return True
            except Exception:
                continue

        return False



    @app.before_request
    def auth_guard():
        # 🔒 Filtrage IP
        client_ip = _get_client_ip()
        if not _ip_allowed(client_ip):
            security_logger.warning("Blocked request | ip=%s | path=%s", client_ip, request.path)
            abort(403)

        s = _get_auth_settings()

        # assets toujours OK
        always_allowed_prefixes = ("/static", "/set_language", "/health")
        if request.path.startswith(always_allowed_prefixes) or request.path in ("/favicon.ico",):
            return

        # si auth désactivée -> open bar
        auth_enabled = s.get("auth_enabled")

        # ⚠️ s.get("auth_enabled") peut valoir 0 (falsy). On ne doit PAS le remplacer par 1 via un "or".
        if int(1 if auth_enabled is None else auth_enabled) == 0:
            return

        configured = _is_auth_configured(s)

        # ✅ IMPORTANT : on ne protège PAS /api (background)
        #if request.path.startswith("/api/"):
        #    return

        # pages auth accessibles
        auth_pages = ("/login", "/logout", "/setup-admin")
        if request.path in auth_pages:
            if request.path == "/login" and not configured:
                return redirect(url_for("setup_admin"))
            return

        # Si pas configuré => forcer setup admin pour toute UI
        if not configured:
            return redirect(url_for("setup_admin"))

        # Si configuré => login obligatoire pour UI
        if not _is_logged_in():
            return redirect(url_for("login", next=request.path))




    # -----------------------------
    # AUTH ROUTES
    # -----------------------------



