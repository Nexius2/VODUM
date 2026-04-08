# Auto-split from app.py (keep URLs/endpoints intact)
from core.i18n import get_translator

from web.filters import cron_human, tz_filter
from web.helpers import get_db, table_exists

def register(app):
    @app.route("/api/tasks/list", methods=["GET"])
    def api_tasks_list():
        db = get_db()

        if not table_exists(db, "tasks"):
            return {"tasks": []}

        t = get_translator()

        rows = db.query(
            """
            SELECT
                id,
                name,
                description,
                schedule,
                status,
                enabled,
                last_run,
                next_run
            FROM tasks
            ORDER BY name
            """
        )

        tasks = []
        for r in rows:
            name = r["name"]
            desc = r["description"]

            # Labels comme dans tasks.html:
            # {{ t("task." ~ task.name) or task.name }}
            # {{ t("task_description." ~ task.name) or task.description or "-" }}
            name_label = t(f"task.{name}") or name
            desc_label = t(f"task_description.{name}") or (desc or "-")

            schedule = r["schedule"] or ""
            schedule_human = cron_human(schedule) if schedule else "-"

            last_run_human = tz_filter(r["last_run"]) if r["last_run"] else "-"
            next_run_human = tz_filter(r["next_run"]) if r["next_run"] else "-"

            tasks.append({
                "id": r["id"],
                "name": name,
                "description": desc,
                "schedule": schedule,
                "status": r["status"],
                "enabled": bool(r["enabled"]),
                "name_label": name_label,
                "description_label": desc_label,
                "schedule_human": schedule_human,
                "last_run_human": last_run_human,
                "next_run_human": next_run_human,
            })

        return {"tasks": tasks}




    @app.route("/api/tasks/activity", methods=["GET"])
    def api_tasks_activity():
        db = get_db()

        if not table_exists(db, "tasks"):
            return {"active": 0, "running": 0, "queued": 0}

        row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
              SUM(CASE WHEN status = 'queued'  THEN 1 ELSE 0 END) AS queued
            FROM tasks
            WHERE status IN ('running', 'queued')
            """
        )

        if row is None:
            return {"active": 0, "running": 0, "queued": 0}

        running = row["running"] or 0
        queued  = row["queued"]  or 0
        active  = running + queued

        return {
            "active": active,
            "running": running,
            "queued": queued
        }







    # -----------------------------
    # ROUTES
    # -----------------------------


