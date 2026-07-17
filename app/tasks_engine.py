import threading
import time
import importlib
from datetime import datetime
import os

from db_manager import DBManager
from logging_utils import get_logger, is_debug_mode_enabled
from core.tasks.scheduler_rules import (
    compute_next_task_run as _compute_next_task_run,
    retry_modifier_for_attempt as _retry_modifier_for_attempt,
)
from core.tasks.result_validation import validate_task_result
from core.tasks.runtime_signals import TaskRuntimeSignals
from core.tasks.sequences import TaskSequenceRunner, discovery_sequence_for_provider
from core.tasks.worker_lease import WorkerLease
from core.tasks.auto_enable import TaskAutoEnableService
from core.tasks.configuration import TaskConfigurationService
from core.tasks.execution import TaskExecutionRunner
from core.tasks.scheduler import TaskScheduler
from core.tasks.runtime import SchedulerRuntime

# -------------------------------------------------------------------
# DB / LOGGER
# -------------------------------------------------------------------
DB_PATH = os.environ.get("DATABASE_PATH", "/appdata/database.db")


class _LazyDB:
    """
    Évite de figer une connexion SQLite au chargement du module.
    La vraie instance DBManager n'est créée qu'au premier usage.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._instance = None
        self._lock = threading.Lock()

    def _get_instance(self):
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = DBManager(self.db_path)
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get_instance(), name)


db = _LazyDB(DB_PATH)

logger = get_logger("tasks_engine")

# -------------------------------------------------------------------
# Global master switch (settings.enable_cron_jobs)
# -------------------------------------------------------------------
def _cron_jobs_enabled() -> bool:
    try:
        row = db.query_one("SELECT enable_cron_jobs FROM settings WHERE id = 1")
        return int(row["enable_cron_jobs"]) == 1 if row and row["enable_cron_jobs"] is not None else True
    except Exception:
        # If settings row doesn't exist yet (fresh DB), don't block tasks_engine
        return True


# -------------------------------------------------------------------
# LOCKS / QUEUES
# -------------------------------------------------------------------
task_worker_lease = WorkerLease()


# In-memory signals are isolated from the scheduler orchestration so their
# thread-safety and consume-once semantics can be tested independently.
runtime_signals = TaskRuntimeSignals()


def mark_auto_enable_dirty():
	runtime_signals.mark_auto_enable_dirty()


def consume_auto_enable_dirty() -> bool:
	return runtime_signals.consume_auto_enable_dirty()

def force_task_run(task_name: str):
	"""
	Force une tâche à être exécutée au prochain tick scheduler,
	sans attendre son prochain cron.
	"""
	runtime_signals.force_task_run(task_name)


def consume_forced_task_run(task_name: str) -> bool:
	"""
	Consomme un forced run.
	Retourne True si la tâche était marquée.
	"""
	return runtime_signals.consume_forced_task_run(task_name)


def _start_task_worker():
    """
    Démarre le worker de tâches.
    L'attribution thread-safe garantit qu'un seul worker est demarre.
    """
    if not task_worker_lease.claim():
        return False

    try:
        threading.Thread(
            target=_task_worker,
            name="vodum-task-worker",
            daemon=True
        ).start()
    except Exception:
        task_worker_lease.release()
        raise
    return True

# -------------------------------------------------------------------
# TASK LIMITS
# -------------------------------------------------------------------
TASK_MAX_DURATION = {
    "sync_plex": 60 * 60,
    "sync_jellyfin": 30 * 60,
    "import_tautulli": 6 * 60 * 60,  # 6h (migration possible, gros volumes)

    # Monitoring / workers : doivent être rapides
    "monitor_collect_sessions": 60,        # 1 min
    "monitor_enqueue_refresh": 60,         # 1 min
    "media_jobs_worker": 120,              # 2 min
    "migration_worker": 30 * 60,
}

DEFAULT_TASK_MAX_DURATION = 30 * 60



def _mark_task_retry_or_error(task_id: int, task_name: str, error_message: str):
    """
    Persiste l'état d'erreur d'une tâche.
    Si des retries restent disponibles, programme un retry via next_retry_at.
    Sinon laisse la tâche en erreur simple.
    """
    try:
        row = db.query_one(
            """
            SELECT retry_count, max_retries
            FROM tasks
            WHERE id = ?
            """,
            (task_id,)
        )

        retry_count = int(row["retry_count"] or 0) if row else 0
        max_retries = int(row["max_retries"] or 0) if row else 0

        next_attempt = retry_count + 1
        can_retry = next_attempt <= max_retries

        if can_retry:
            modifier = _retry_modifier_for_attempt(next_attempt)
            db.execute(
                """
                UPDATE tasks
                SET
                    status = CASE WHEN queued_count > 0 THEN 'queued' ELSE 'error' END,
                    last_run = datetime('now'),
                    last_error = ?,
                    retry_count = ?,
                    next_retry_at = datetime('now', ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(error_message), next_attempt, modifier, task_id)
            )

            logger.warning(
                f"Task '{task_name}' failed -> retry scheduled "
                f"(attempt {next_attempt}/{max_retries})"
            )
            task_logs(
                task_id,
                "warning",
                f"Task '{task_name}' failed -> retry scheduled ({next_attempt}/{max_retries})",
                details={"error": str(error_message), "next_retry_in": modifier},
            )
        else:
            db.execute(
                """
                UPDATE tasks
                SET
                    status = CASE WHEN queued_count > 0 THEN 'queued' ELSE 'error' END,
                    last_run = datetime('now'),
                    last_error = ?,
                    next_retry_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(error_message), task_id)
            )

            logger.error(
                f"Task '{task_name}' failed with no retry left "
                f"(attempts exhausted: {retry_count}/{max_retries})"
            )
            task_logs(
                task_id,
                "error",
                f"Task '{task_name}' failed with no retry left",
                details={"error": str(error_message), "retry_count": retry_count, "max_retries": max_retries},
            )

    except Exception as persist_exc:
        logger.error(
            f"Unable to persist retry/error state for task '{task_name}' (id={task_id}): {persist_exc}",
            exc_info=True,
        )

# -------------------------------------------------------------------
# Compatibilité avec app.py (ne rien changer)
# -------------------------------------------------------------------




def run_task_by_name(task_name: str):
    if not _cron_jobs_enabled():
        if is_debug_mode_enabled():
            logger.debug(f"Cron disabled (global); ignoring manual run: {task_name}")
        return False

    row = db.query_one(
        "SELECT id, status, enabled FROM tasks WHERE name = ?",
        (task_name,)
    )

    if not row:
        logger.error(f"Unknown task: {task_name}")
        return False

    if not row["enabled"]:
        logger.warning(f"disabled task: {task_name}")
        return False

    task_id = row["id"]
    enqueue_task(task_id)
    return True


def enable_and_run_task_by_name(task_name: str):
    row = db.query_one(
        """
        SELECT id, enabled, status, queued_count
        FROM tasks
        WHERE name = ?
        """,
        (task_name,),
    )

    if not row:
        logger.error(f"Unknown task: {task_name}")
        return False

    task_id = row["id"]
    status = str(row["status"] or "").lower()
    queued_count = int(row["queued_count"] or 0)

    if not row["enabled"]:
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1,
                status = CASE
                    WHEN status = 'disabled' THEN 'idle'
                    WHEN status IS NULL OR TRIM(status) = '' THEN 'idle'
                    ELSE status
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )

    if status == "running" or queued_count > 0:
        if is_debug_mode_enabled():
            logger.debug(f"Task '{task_name}' already running or queued; not enqueueing again")
        return True

    return enqueue_task(task_id)

configuration_service = TaskConfigurationService(db)


def set_task_enabled(task_id: int, enabled: int):
    return configuration_service.set_task_enabled(task_id, enabled)


def set_tasks_enabled_by_names(task_names, enabled: int):
    return configuration_service.set_tasks_enabled_by_names(task_names, enabled)


def set_task_enabled_for_auto_mode(task_id: int, enabled: int):
    return configuration_service.set_task_enabled_for_auto_mode(task_id, enabled)


def set_tasks_enabled_by_names_for_auto_mode(task_names, enabled: int):
    return configuration_service.set_tasks_enabled_by_names_for_auto_mode(task_names, enabled)


def ensure_tasks_enabled(task_names):
    return configuration_service.ensure_tasks_enabled(task_names)


def apply_cron_master_switch(enabled: int):
    return configuration_service.apply_cron_master_switch(enabled)


def sync_expiry_tasks_from_settings(expiry_mode: str, cron_enabled: int):
    return configuration_service.sync_expiry_tasks_from_settings(expiry_mode, cron_enabled)


def prepare_restored_database(restored_db):
    return configuration_service.prepare_restored_database(restored_db)

# -------------------------------------------------------------------
# Watchdog
# -------------------------------------------------------------------


def recover_stuck_tasks(max_minutes=30):
    # A live worker may legitimately own a long-running task. Resetting its DB
    # state here would allow the scheduler to enqueue a duplicate execution.
    if task_worker_lease.is_claimed():
        return

    try:
        row = db.query_one(
            """
            SELECT COUNT(*) AS cnt
            FROM tasks
            WHERE status = 'running'
              AND datetime(updated_at) < datetime('now', ?)
            """,
            (f'-{max_minutes} minutes',)
        )

        if not row or int(row["cnt"] or 0) <= 0:
            return
        db.execute(
            """
            UPDATE tasks
            SET
                status = 'idle',
                last_error = 'Watchdog: task was stuck in running state',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
              AND datetime(updated_at) < datetime('now', ?)
            """,
            (f'-{max_minutes} minutes',)
        )
    except Exception as e:
        logger.error(f"[WATCHDOG] failed to recover tasks: {e}")







def _watchdog_loop():
    while True:
        recover_stuck_tasks()
        time.sleep(300)


# -------------------------------------------------------------------
# Logging unifié des tâches
# -------------------------------------------------------------------
def task_logs(task_id, status, message, details=None, debug_only=False):

    if debug_only and not is_debug_mode_enabled():
        return

    status_l = str(status).lower().strip()

    level = "info"
    label = "INFO"

    if status_l in ("debug", "noop", "idle", "skip", "skipped"):
        if not is_debug_mode_enabled():
            return
        level = "debug"
        label = "DEBUG"

    elif status_l in ("start", "starting", "running", "begin", "launch", "launched"):
        level = "info"
        label = "START"

    elif status_l in ("success", "ok", "done", "finished"):
        level = "info"
        label = "SUCCESS"

    elif status_l in ("warn", "warning"):
        level = "warning"
        label = "WARNING"

    elif status_l in ("error", "err", "failed", "ko", "timeout"):
        level = "error"
        label = "ERROR"

    elif status_l == "info" and not is_debug_mode_enabled():
        return

    log_msg = f"[TASK {task_id}] {label}: {message}"

    if details is not None:
        if not isinstance(details, str):
            try:
                import json
                details = json.dumps(details, ensure_ascii=False)
            except Exception:
                details = str(details)

        log_msg += f" | details={details}"

    if level == "error":
        logger.error(log_msg)
    elif level == "warning":
        logger.warning(log_msg)
    elif level == "debug":
        logger.debug(log_msg)
    else:
        logger.info(log_msg)



def mark_task_manual_run_requested(task_id: int):
    """
    Prépare l'état d'une tâche avant un run manuel depuis l'UI.
    """
    db.execute(
        """
        UPDATE tasks
        SET status = CASE
                WHEN status = 'running' THEN status
                ELSE 'queued'
            END,
            last_error = NULL,
            next_retry_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (task_id,),
    )
    return True


def mark_task_queue_failed(task_id: int, error_message: str):
    """
    Persiste un échec de mise en file depuis l'UI.
    """
    db.execute(
        """
        UPDATE tasks
        SET status = 'error',
            last_error = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (str(error_message), task_id),
    )
    return True


def enqueue_task(task_id: int):
    if not _cron_jobs_enabled():
        if is_debug_mode_enabled():
            logger.info(f"Cron disabled (global); ignoring enqueue for task_id={task_id}")
        return False

    row = db.query_one(
        "SELECT enabled FROM tasks WHERE id = ?",
        (task_id,)
    )
    if not row or not row["enabled"]:
        if is_debug_mode_enabled():
            logger.debug(f"Task {task_id} ignored (disabled)")
        return False

    db.execute(
        """
        UPDATE tasks
        SET queued_count = CASE
                WHEN queued_count > 0 THEN queued_count
                ELSE 1
            END,
            status = CASE
                WHEN status = 'running' THEN 'running'
                ELSE 'queued'
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND enabled = 1
        """,
        (task_id,)
    )

    # Démarrage du worker SI nécessaire
    _start_task_worker()

    return True

def _kick_worker_if_needed():
    """
    Si la DB contient des tâches en attente (queued_count > 0) et que le worker
    n'est pas en cours, on le démarre.

    Important: au boot, le recovery peut laisser des tasks en 'queued' sans
    jamais repasser par enqueue_task() -> donc sans démarrer le worker.
    """
    # -------------------------------------------------
    # Worker déjà actif → inutile de requêter SQLite
    # -------------------------------------------------
    if task_worker_lease.is_claimed():
        return

    try:
        row = db.query_one("SELECT COUNT(*) AS cnt FROM tasks WHERE queued_count > 0 AND enabled = 1")
        pending = int(row["cnt"]) if row else 0
    except Exception as e:
        logger.error(f"[WORKER] Unable to check pending queue: {e}", exc_info=True)
        return

    if pending <= 0:
        return

    if _start_task_worker():
        logger.warning(f"[WORKER] Kick worker: {pending} queued task(s) detected in DB")


def _task_worker():
    try:
        while True:
            # 1) Récupère une tâche en file d'attente
            try:
                row = db.query_one(
                    """
                    SELECT id
                    FROM tasks
                    WHERE queued_count > 0
                      AND enabled = 1
                      ORDER BY
                          CASE name
                              WHEN 'monitor_enqueue_refresh' THEN 1
                              WHEN 'media_jobs_worker' THEN 2
                              WHEN 'stream_enforcer' THEN 3
                              WHEN 'monitor_collect_sessions' THEN 99
                              ELSE 10
                        END ASC,
                        updated_at ASC,
                        id ASC
                    LIMIT 1
                    """
                )
            except Exception as e:
                logger.error(f"[WORKER] DB error while fetching queued task: {e}", exc_info=True)
                return

            # 2) Plus rien à traiter => on sort et on libère le worker
            if not row:
                return

            task_id = int(row["id"])

            # 3) Exécute réellement la tâche
            try:
                run_task(task_id)
            except Exception as e:
                # run_task gère déjà beaucoup de cas, mais on sécurise
                logger.error(f"[WORKER] Unhandled error while running task id={task_id}: {e}", exc_info=True)
                try:
                    task_logs(task_id, "error", f"Unhandled worker error: {e}")
                except Exception as log_exc:
                    logger.warning(
                        f"[WORKER] Unable to write task_logs for task id={task_id}: {log_exc}",
                        exc_info=True,
                    )

            # 4) Petite pause pour éviter de marteler la DB
            time.sleep(0.2)

    finally:
        # GARANTIE : le worker se libère toujours
        task_worker_lease.release()

        # Si une tâche a été ajoutée juste avant l'arrêt du worker,
        # on relance immédiatement un worker pour ne rien laisser bloqué.
        _kick_worker_if_needed()





# -------------------------------------------------------------------
# Exécution d'une tâche
# -------------------------------------------------------------------
def _load_task_run_callable(task_name: str):
    module_name = f"tasks.{task_name}"

    try:
        module = importlib.import_module(module_name)
        if not hasattr(module, "run"):
            raise AttributeError(f"Le module {module_name} n'expose pas run()")
        return module.run
    except Exception as e:
        raise RuntimeError(f"Unable to load {module_name}: {e}") from e


def _execute_task_run_callable(run_func, task_id: int, task_name: str, max_duration: int):
    """
    Execute the task inside the single scheduler worker.

    Python cannot safely stop a timed-out thread. The previous helper allowed
    that thread to continue while the worker started following tasks, creating
    hidden concurrency. Duration is still checked after return by
    _process_task_result(), without allowing scheduler tasks to overlap.
    """
    return run_func(task_id, db)


def _handle_task_success(task_id: int, task_name: str, schedule):
    """
    Persiste le succès d'une tâche, applique les post-traitements éventuels,
    puis recalcule le prochain run si la tâche est planifiée.
    """
    db.execute(
        """
        UPDATE tasks
        SET
            status = CASE WHEN queued_count > 0 THEN 'queued' ELSE 'idle' END,
            last_run = datetime('now'),
            last_error = NULL,
            retry_count = 0,
            next_retry_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (task_id,)
    )

    if is_debug_mode_enabled():
        logger.debug(f"Task '{task_name}' completed successfully.")

    task_logs(
        task_id,
        "success",
        f"Task '{task_name}' completed successfully",
        debug_only=True
    )

    if task_name == "check_servers":
        if is_debug_mode_enabled():
            logger.debug("Auto re-evaluating sync tasks after check_servers")
        task_logs(task_id, "info", "Sync tasks auto re-evaluation")

        try:
            auto_enable_sync_tasks()
        except Exception as e:
            logger.error(f"Sync re-evaluation failed: {e}", exc_info=True)
            task_logs(task_id, "warning", f"Sync re-evaluation failed: {e}")

        try:
            auto_enable_monitoring_tasks()
        except Exception as e:
            logger.error(f"Enable monitoring failed: {e}", exc_info=True)
            task_logs(task_id, "warning", f"Sync monitoring failed: {e}")

    if schedule:
        try:

            task_row = db.query_one(
                """
                SELECT schedule_mode, interval_seconds
                FROM tasks
                WHERE id = ?
                """,
                (task_id,)
            )

            schedule_mode = (
                task_row["schedule_mode"]
                if task_row and task_row["schedule_mode"]
                else "cron"
            )

            interval_seconds = (
                task_row["interval_seconds"]
                if task_row
                else None
            )

            now = datetime.now()

            next_exec = _compute_next_task_run(
                schedule,
                schedule_mode,
                interval_seconds,
                now,
            )

            db.execute(
                "UPDATE tasks SET next_run=? WHERE id=?",
                (next_exec, task_id)
            )

            if is_debug_mode_enabled():
                logger.debug(f"Next run '{task_name}' → {next_exec}")
                task_logs(task_id, "info", f"Next run '{task_name}' → {next_exec}")

        except Exception as e:
            logger.error(f"Schedule error after execution: {e}")
            task_logs(task_id, "warning", f"Schedule error after execution: {e}")





def _mark_task_running(task_id: int):
    """
    Passe une tâche en running et consomme 1 élément de queue.
    """
    db.execute(
        """
        UPDATE tasks
        SET
            status = 'running',
            last_error = NULL,
            last_attempt_at = datetime('now'),
            next_retry_at = NULL,
            queued_count = CASE
                WHEN queued_count > 0 THEN queued_count - 1
                ELSE 0
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (task_id,)
    )
    return True


def _finalize_task_running_failsafe(task_id: int):
    """
    Corrige une tâche restée bloquée en RUNNING si aucun autre état
    n'a été persisté explicitement.
    """
    row = db.query_one(
        "SELECT status FROM tasks WHERE id = ?",
        (task_id,)
    )

    if row and row["status"] == "running":
        db.execute(
            """
            UPDATE tasks
            SET
                status = 'idle',
                last_error = COALESCE(
                    last_error,
                    'Failsafe: task exited without explicit status update'
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,)
        )

        logger.warning(
            f"[FAILSAFE] Task {task_id} fixed (left in RUNNING state)"
        )

    return True

def _load_task_execution_context(task_id: int):
    """
    Charge le contexte minimal nécessaire à l'exécution d'une tâche.
    Retourne None si la tâche n'existe plus.
    """
    row = db.query_one(
        """
        SELECT id, name, schedule, status, retry_count, max_retries, next_retry_at
        FROM tasks
        WHERE id = ?
        """,
        (task_id,)
    )

    if not row:
        logger.error(f"TASK {task_id} missing.")
        task_logs(task_id, "error", "task missing in DB")
        return None

    name = row["name"]
    schedule = row["schedule"]
    max_duration = TASK_MAX_DURATION.get(name, DEFAULT_TASK_MAX_DURATION)

    return {
        "row": row,
        "name": name,
        "schedule": schedule,
        "max_duration": max_duration,
    }


def _process_task_result(task_id: int, task_name: str, result, start_time: float, max_duration: int):
    """
    Post-traite le résultat d'une tâche :
    - log éventuel du payload retourné
    - contrôle du timeout réel
    - transforme un retour {'status': 'error'} en vraie erreur
    """
    if result is not None:
        try:
            if result:
                if is_debug_mode_enabled():
                    logger.debug(f"Task '{task_name}' returned data")

                task_logs(
                    task_id,
                    "info",
                    f"Task '{task_name}' returned data",
                    debug_only=True
                )

            task_logs(
                task_id,
                "info",
                f"Task '{task_name}' returned",
                details=result,
                debug_only=True
            )

        except Exception as log_exc:
            logger.warning(
                f"Unable to log task return payload for '{task_name}' (id={task_id}): {log_exc}",
                exc_info=True,
            )

    return validate_task_result(
        task_name,
        result,
        time.time() - start_time,
        max_duration,
    )

def run_task(task_id: int):
    return task_execution_runner.run(task_id)

task_execution_runner = TaskExecutionRunner(
    db,
    _load_task_execution_context,
    _mark_task_running,
    _handle_task_success,
    _mark_task_retry_or_error,
    _finalize_task_running_failsafe,
    task_logs,
    logger,
    is_debug_mode_enabled,
)

sequence_runner = TaskSequenceRunner(db, enqueue_task, logger, is_debug_mode_enabled)


def wait_for_task_completion(task_name, last_run_before=None, poll_interval=2, timeout=1800):
    return sequence_runner.wait_for_completion(task_name, last_run_before, poll_interval, timeout)


def run_task_sequence(task_names):
    return sequence_runner.enqueue(task_names)


def enqueue_server_discovery_sequence(server_type: str):
    run_task_sequence(discovery_sequence_for_provider(server_type))
    return True


auto_enable_service = TaskAutoEnableService(
    db,
    set_task_enabled_for_auto_mode,
    set_tasks_enabled_by_names_for_auto_mode,
    sync_expiry_tasks_from_settings,
    force_task_run,
    logger,
)


def auto_enable_monitoring_tasks():
    return auto_enable_service.monitoring()

def auto_enable_sync_tasks():
    return auto_enable_service.sync_providers()

def auto_enable_plex_jobs_worker():
    return auto_enable_service.access_worker("plex")

def auto_enable_jellyfin_jobs_worker():
    return auto_enable_service.access_worker("jellyfin")

def auto_enable_stream_enforcer():
    return auto_enable_service.stream_enforcer()

def run_auto_enable_pass():
    return auto_enable_service.run_pass()

task_scheduler = TaskScheduler(
    db,
    enqueue_task,
    _compute_next_task_run,
    consume_forced_task_run,
    run_auto_enable_pass,
    logger,
)

scheduler_runtime = SchedulerRuntime(
    db, task_scheduler, _cron_jobs_enabled, _kick_worker_if_needed,
    consume_auto_enable_dirty, run_auto_enable_pass, _watchdog_loop,
    _compute_next_task_run, logger, is_debug_mode_enabled,
)


def _recover_scheduler_state_at_boot():
    return scheduler_runtime.recover_state()


def _run_scheduler_tick(now, run_auto_enable=True):
    return task_scheduler.tick(now, run_auto_enable=run_auto_enable)


def scheduler_loop():
    return scheduler_runtime.loop()


def force_check_update_at_startup():
    return scheduler_runtime.force_check_update()


def start_scheduler():
    return scheduler_runtime.start()
