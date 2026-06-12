from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = (ROOT / "app" / "tasks_engine.py").read_text(encoding="utf-8")
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
TASKS_API = (ROOT / "app" / "routes" / "tasks_api.py").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "app" / "db_bootstrap.py").read_text(encoding="utf-8")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


require(
    "WHEN queued_count > 0 THEN queued_count" in ENGINE,
    "enqueue_task must coalesce repeated pending executions",
)
require(
    "return run_func(task_id, db)" in ENGINE,
    "scheduled task execution must remain sequential",
)
watchdog = ENGINE.split("def recover_stuck_tasks", 1)[1].split("def _watchdog_loop", 1)[0]
require(
    "if worker_running:" in watchdog,
    "watchdog must not reset a task owned by the live worker",
)
require(
    'id="taskActivityText"' in BASE
    and "data.running" in APP_JS
    and "data.queued" in APP_JS,
    "task activity UI must distinguish running and queued tasks",
)
require(
    'data-label="{{ t(\'task_activity_label\') }}"' in BASE
    and "textEl.dataset.label" in APP_JS,
    "task activity UI must clearly identify that the counts refer to tasks",
)
require(
    "COALESCE(queued_count, 0) > 0" in TASKS_API,
    "task activity API must count the persisted queue, including reruns",
)
require(
    "TASK_DEFAULTS_VERSION = 3" in BOOTSTRAP
    and '"sync_plex": "7 */6 * * *"' in BOOTSTRAP
    and '"sync_jellyfin": "17 */6 * * *"' in BOOTSTRAP
    and '"update_user_status": "5 * * * *"' in BOOTSTRAP,
    "heavy and hourly default schedules must remain staggered",
)

print("task queue safety validation: OK")
