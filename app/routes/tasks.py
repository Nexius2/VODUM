# Auto-split from app.py (keep URLs/endpoints intact)
import json

from flask import (
    render_template, request, redirect, url_for, flash, jsonify,
)

from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import (
    enqueue_task,
    set_task_enabled,
    set_tasks_enabled_by_names,
    mark_task_manual_run_requested,
    mark_task_queue_failed,
)
from web.helpers import get_db, table_exists, add_log
from notifications_utils import is_email_ready

task_logger = get_logger("tasks_ui")

TASKS_PAGE_COLUMNS = """
    id,
    name,
    description,
    schedule,
    status,
    enabled,
    last_run,
    next_run
"""


def register(app):
    @app.route("/tasks", methods=["GET"])
    def tasks_page():
        db = get_db()

        debug_mode = is_debug_mode_enabled()

        tasks = []
        if table_exists(db, "tasks"):
            if debug_mode:
                tasks = db.query(
                    f"""
                    SELECT {TASKS_PAGE_COLUMNS}
                    FROM tasks
                    ORDER BY name
                    """
                )
            else:
                tasks = db.query(
                    f"""
                    SELECT {TASKS_PAGE_COLUMNS}
                    FROM tasks
                    WHERE enabled = 1
                    ORDER BY name
                    """
                )
        
        if debug_mode:
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

        task = db.query_one("SELECT id, enabled FROM tasks WHERE id = ?", (task_id,))
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
                    task_logger.exception(
                        "Unable to persist task queue failure | task_id=%s | task_name=%s",
                        task_id,
                        name,
                    )

            return redirect(url_for("tasks_page"))

        task_logger.warning(f"Action inconnue sur /tasks/action : {action} (task_id={task_id})")
        flash("unknown_action", "error")
        return redirect(url_for("tasks_page"))




    # -----------------------------
    # MAILING
    # -----------------------------
    
    def is_smtp_ready(settings) -> bool:
        return is_email_ready(settings)


    
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
                ["send_expiration_emails", "send_comm_campaigns"],
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
    # AUTH ROUTES
    # -----------------------------
