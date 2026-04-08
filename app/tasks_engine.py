import threading
import time
import importlib
from datetime import datetime
from croniter import croniter
import os

from db_manager import DBManager
from logging_utils import get_logger

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
sequence_lock = threading.Lock()

sequence_queue = []
sequence_thread_running = False

queue_lock = threading.Lock()
worker_running = False
scheduler_start_lock = threading.Lock()
scheduler_started = False


def _start_task_worker_locked():
    """
    Démarre le worker de tâches.
    Cette fonction suppose que queue_lock est déjà pris.
    """
    global worker_running

    if worker_running:
        return False

    worker_running = True
    threading.Thread(
        target=_task_worker,
        name="vodum-task-worker",
        daemon=True
    ).start()
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
}

DEFAULT_TASK_MAX_DURATION = 30 * 60

def _retry_modifier_for_attempt(next_attempt_number: int) -> str:
    """
    Backoff simple et standard pour les tâches scheduler :
    1 -> +1 minute
    2 -> +5 minutes
    3 -> +15 minutes
    4+ -> +30 minutes
    """
    if next_attempt_number <= 1:
        return "+1 minute"
    if next_attempt_number == 2:
        return "+5 minutes"
    if next_attempt_number == 3:
        return "+15 minutes"
    return "+30 minutes"


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
        logger.info(f"Cron disabled (global); ignoring manual run: {task_name}")
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
    """
    Active une tâche si besoin, normalise son statut si elle était disabled,
    puis l'ajoute proprement à la file via run_task_by_name().
    """
    row = db.query_one(
        "SELECT id, status, enabled FROM tasks WHERE name = ?",
        (task_name,)
    )

    if not row:
        logger.error(f"Unknown task: {task_name}")
        return False

    if not row["enabled"] or (row["status"] or "") == "disabled":
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
            (row["id"],),
        )

    return run_task_by_name(task_name)

def set_task_enabled(task_id: int, enabled: int):
    """
    Active ou désactive une tâche par ID avec un état cohérent.
    """
    enabled = 1 if int(enabled) == 1 else 0

    if enabled == 1:
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1,
                status = 'idle',
                last_error = NULL,
                next_run = NULL,
                retry_count = 0,
                next_retry_at = NULL,
                last_attempt_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )
    else:
        db.execute(
            """
            UPDATE tasks
            SET enabled = 0,
                status = 'disabled',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )

    return True


def set_tasks_enabled_by_names(task_names, enabled: int):
    """
    Active ou désactive plusieurs tâches par nom avec un état cohérent.
    """
    if not task_names:
        return False

    enabled = 1 if int(enabled) == 1 else 0
    placeholders = ",".join("?" for _ in task_names)

    db.execute(
        f"""
        UPDATE tasks
        SET enabled = ?,
            status = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE name IN ({placeholders})
        """,
        (enabled, enabled, *task_names),
    )

    return True

def set_task_enabled_for_auto_mode(task_id: int, enabled: int):
    """
    Active/désactive une tâche dans le cadre d'un auto-enable périodique.

    Important :
    - en ENABLE : on ne reset PAS next_run / retry_count / next_retry_at / last_attempt_at
    - on ne casse PAS running / queued / error
    - en DISABLE : on n'écrase PAS une tâche déjà running/queued
    """
    enabled = 1 if int(enabled) == 1 else 0

    if enabled == 1:
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
    else:
        db.execute(
            """
            UPDATE tasks
            SET enabled = 0,
                status = CASE
                    WHEN status IN ('running', 'queued') THEN status
                    ELSE 'disabled'
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )

    return True


def set_tasks_enabled_by_names_for_auto_mode(task_names, enabled: int):
    """
    Variante multi-tâches du mode auto-enable.
    Préserve l'état utile lors d'une activation périodique.
    """
    if not task_names:
        return False

    enabled = 1 if int(enabled) == 1 else 0
    placeholders = ",".join("?" for _ in task_names)

    if enabled == 1:
        db.execute(
            f"""
            UPDATE tasks
            SET enabled = 1,
                status = CASE
                    WHEN status = 'disabled' THEN 'idle'
                    WHEN status IS NULL OR TRIM(status) = '' THEN 'idle'
                    ELSE status
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE name IN ({placeholders})
            """,
            tuple(task_names),
        )
    else:
        db.execute(
            f"""
            UPDATE tasks
            SET enabled = 0,
                status = CASE
                    WHEN status IN ('running', 'queued') THEN status
                    ELSE 'disabled'
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE name IN ({placeholders})
            """,
            tuple(task_names),
        )

    return True

def ensure_tasks_enabled(task_names):
    """
    Active plusieurs tâches sans écraser un état déjà valide.

    Règle :
    - disabled / vide / NULL -> idle
    - idle / queued / running / error -> conservé
    """
    if not task_names:
        return False

    placeholders = ",".join("?" for _ in task_names)

    db.execute(
        f"""
        UPDATE tasks
        SET enabled = 1,
            status = CASE
                WHEN status = 'disabled' THEN 'idle'
                WHEN status IS NULL OR TRIM(status) = '' THEN 'idle'
                ELSE status
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE name IN ({placeholders})
        """,
        tuple(task_names),
    )

    return True

def apply_cron_master_switch(enabled: int):
    """
    Applique le switch global settings.enable_cron_jobs.

    - OFF : mémorise enabled -> enabled_prev (une seule fois), puis désactive tout
    - ON  : restaure enabled depuis enabled_prev si présent, puis vide enabled_prev
    """
    enabled = 1 if int(enabled) == 1 else 0

    if enabled == 0:
        db.execute(
            """
            UPDATE tasks
            SET
                enabled_prev = CASE
                    WHEN enabled_prev IS NULL THEN enabled
                    ELSE enabled_prev
                END,
                enabled = 0,
                status = 'disabled',
                updated_at = CURRENT_TIMESTAMP
            """
        )
    else:
        db.execute(
            """
            UPDATE tasks
            SET
                enabled = CASE
                    WHEN enabled_prev IS NULL THEN enabled
                    ELSE enabled_prev
                END,
                status = CASE
                    WHEN (CASE WHEN enabled_prev IS NULL THEN enabled ELSE enabled_prev END) = 1 THEN 'idle'
                    ELSE 'disabled'
                END,
                enabled_prev = NULL,
                updated_at = CURRENT_TIMESTAMP
            """
        )

    return True


def sync_expiry_tasks_from_settings(expiry_mode: str, cron_enabled: int):
    """
    Synchronise les tâches liées aux expirations depuis les settings.

    - expiry_mode = 'disable'            -> disable_expired_users = ON
    - expiry_mode = 'warn_then_disable'  -> expired_subscription_manager = ON
    - sinon                              -> les deux OFF

    Si cron est OFF, on ne réactive pas les tâches :
    on stocke uniquement l'état désiré dans enabled_prev.
    """
    expiry_mode = (expiry_mode or "none").strip()
    cron_enabled = 1 if int(cron_enabled) == 1 else 0

    disable_task_enabled = 1 if expiry_mode == "disable" else 0
    warn_task_enabled = 1 if expiry_mode == "warn_then_disable" else 0

    if cron_enabled == 1:
        row_disable = db.query_one(
            "SELECT id FROM tasks WHERE name = 'disable_expired_users'"
        )
        if row_disable:
            set_task_enabled(int(row_disable["id"]), disable_task_enabled)

        row_warn = db.query_one(
            "SELECT id FROM tasks WHERE name = 'expired_subscription_manager'"
        )
        if row_warn:
            set_task_enabled(int(row_warn["id"]), warn_task_enabled)
    else:
        db.execute(
            "UPDATE tasks SET enabled_prev = ? WHERE name = 'disable_expired_users'",
            (disable_task_enabled,),
        )
        db.execute(
            "UPDATE tasks SET enabled_prev = ? WHERE name = 'expired_subscription_manager'",
            (warn_task_enabled,),
        )

    return True

def prepare_restored_database(restored_db):
    """
    Prépare une base fraîchement restaurée :
    - force le maintenance_mode
    - désactive toutes les tâches en mémorisant l'état précédent
    """
    restored_db.execute(
        """
        UPDATE settings
        SET maintenance_mode = 1
        WHERE id = 1
        """
    )

    restored_db.execute(
        """
        UPDATE tasks
        SET
            enabled_prev = CASE
                WHEN enabled_prev IS NULL THEN enabled
                ELSE enabled_prev
            END,
            enabled = 0,
            status = 'disabled',
            updated_at = CURRENT_TIMESTAMP
        """
    )

    return True

# -------------------------------------------------------------------
# Watchdog
# -------------------------------------------------------------------


def recover_stuck_tasks(max_minutes=30):
    try:
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
        time.sleep(30)


# -------------------------------------------------------------------
# Logging unifié des tâches
# -------------------------------------------------------------------
def task_logs(task_id, status, message, details=None):

    # Mapping status → level + label lisible
    status_l = str(status).lower().strip()

    level = "info"
    label = "INFO"

    if status_l in ("start", "starting", "running", "begin", "launch", "launched"):
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

    # Construction message
    log_msg = f"[TASK {task_id}] {label}: {message}"

    if details is not None:
        # évite les logs illisibles quand details est un dict/list
        if not isinstance(details, str):
            try:
                import json
                details = json.dumps(details, ensure_ascii=False)
            except Exception:
                details = str(details)
        log_msg += f" | details={details}"

    # Dispatch vers logging_utils
    if level == "error":
        logger.error(log_msg)
    elif level == "warning":
        logger.warning(log_msg)
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
        logger.info(f"Cron disabled (global); ignoring enqueue for task_id={task_id}")
        return False

    row = db.query_one(
        "SELECT enabled FROM tasks WHERE id = ?",
        (task_id,)
    )
    if not row or not row["enabled"]:
        logger.info(f"Task {task_id} ignored (disabled)")
        return False

    global worker_running

    db.execute(
        """
        UPDATE tasks
        SET queued_count = queued_count + 1,
            status = CASE
                WHEN status IN ('idle', 'error') THEN 'queued'
                ELSE status
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND enabled = 1
        """,
        (task_id,)
    )

    # Démarrage du worker SI nécessaire
    with queue_lock:
        _start_task_worker_locked()

    return True

def _kick_worker_if_needed():
    """
    Si la DB contient des tâches en attente (queued_count > 0) et que le worker
    n'est pas en cours, on le démarre.

    Important: au boot, le recovery peut laisser des tasks en 'queued' sans
    jamais repasser par enqueue_task() -> donc sans démarrer le worker.
    """
    global worker_running

    try:
        row = db.query_one("SELECT COUNT(*) AS cnt FROM tasks WHERE queued_count > 0 AND enabled = 1")
        pending = int(row["cnt"]) if row else 0
    except Exception as e:
        logger.error(f"[WORKER] Unable to check pending queue: {e}", exc_info=True)
        return

    if pending <= 0:
        return

    with queue_lock:
        if _start_task_worker_locked():
            logger.warning(f"[WORKER] Kick worker: {pending} queued task(s) detected in DB")


def _task_worker():
    global worker_running

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
                    ORDER BY updated_at ASC
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
        with queue_lock:
            worker_running = False

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
    result_box = {"value": None, "exc": None}

    def _runner():
        try:
            result_box["value"] = run_func(task_id, db)
        except Exception as e:
            result_box["exc"] = e

    t = threading.Thread(
        target=_runner,
        name=f"vodum-task-{task_name}-{task_id}",
        daemon=True
    )
    t.start()
    t.join(timeout=max_duration)

    if t.is_alive():
        raise TimeoutError(f"Task {task_name} exceeded maximum duration ({max_duration}s)")

    if result_box["exc"] is not None:
        raise result_box["exc"]

    return result_box["value"]


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

    logger.info(f"Task '{task_name}' completed successfully.")
    task_logs(task_id, "success", f"Task '{task_name}' completed successfully")

    if task_name == "check_servers":
        logger.info("Auto re-evaluating sync tasks after check_servers")
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
            itr = croniter(schedule, datetime.now())
            next_exec = itr.get_next(datetime)

            db.execute(
                "UPDATE tasks SET next_run=? WHERE id=?",
                (next_exec, task_id)
            )

            logger.info(f"Next run '{task_name}' → {next_exec}")
            task_logs(task_id, "info", f"Next run '{task_name}' → {next_exec}")
        except Exception as e:
            logger.error(f"Cron error after execution: {e}")
            task_logs(task_id, "warning", f"Cron error after execution: {e}")





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
            logger.info(f"Task '{task_name}' returned: {result}")
            task_logs(task_id, "info", f"Task '{task_name}' returned", details=result)
        except Exception as log_exc:
            logger.warning(
                f"Unable to log task return payload for '{task_name}' (id={task_id}): {log_exc}",
                exc_info=True,
            )

    duration = time.time() - start_time
    if duration > max_duration:
        raise TimeoutError(
            f"Task {task_name} exceeded maximum duration ({int(duration)}s > {max_duration}s)"
        )

    if isinstance(result, dict):
        returned_status = str(result.get("status") or "").strip().lower()
        if returned_status == "error":
            returned_error = (
                result.get("message")
                or result.get("error")
                or f"Task {task_name} returned status=error"
            )
            raise RuntimeError(str(returned_error))

    return result

def run_task(task_id: int):
    ctx = _load_task_execution_context(task_id)
    if not ctx:
        return

    name = ctx["name"]
    schedule = ctx["schedule"]
    max_duration = ctx["max_duration"]

    logger.info(f"Starting task '{name}' (id={task_id})")
    task_logs(task_id, "start", f"Starting task '{name}'")

    start_time = time.time()

    # -------------------------------------------------
    # Passage en RUNNING (et consomme 1 élément de queue)
    # -------------------------------------------------
    try:
        _mark_task_running(task_id)
    except Exception as e:
        logger.error(f"Erreur passage en running : {e}")
        task_logs(task_id, "error", f"Erreur passage en running: {e}")
        return

    # -------------------------------------------------
    # Import dynamique
    # -------------------------------------------------
    try:
        run_func = _load_task_run_callable(name)
    except Exception as e:
        msg = str(e)
        logger.error(msg)
        task_logs(task_id, "error", msg)
        _mark_task_retry_or_error(task_id, name, str(e))
        return

    # -------------------------------------------------
    # Exécution réelle
    # -------------------------------------------------
    try:
        logger.debug(f"Calling run() for task '{name}'")

        result = _execute_task_run_callable(run_func, task_id, name, max_duration)
        _process_task_result(task_id, name, result, start_time, max_duration)

        # ---- SUCCÈS ----
        _handle_task_success(task_id, name, schedule)

    except Exception as e:
        msg = f"Error while running {name}: {e}"
        logger.error(msg, exc_info=True)
        task_logs(task_id, "error", msg)
        _mark_task_retry_or_error(task_id, name, str(e))

    finally:
        # -------------------------------------------------
        # FAILSAFE FINAL STRICT
        # -------------------------------------------------
        try:
            _finalize_task_running_failsafe(task_id)
        except Exception as e:
            logger.error(
                f"[FAILSAFE] Unable to fix task {task_id}: {e}"
            )
            task_logs(task_id, "warning", f"Failsafe final failed: {e}")

def wait_for_task_completion(task_name, last_run_before=None, poll_interval=2, timeout=1800):
    """
    Attend qu'une tâche ait VRAIMENT exécuté au moins une fois après un enqueue.

    - Si last_run_before est fourni : on attend que last_run change (recommandé).
    - Sinon : fallback historique (idle/error), mais moins fiable.
    """
    start = time.time()

    while True:
        row = db.query_one(
            "SELECT status, last_run FROM tasks WHERE name=?",
            (task_name,)
        )

        if not row:
            return  # tâche inconnue => on considère terminé

        status = (row["status"] or "").lower().strip()
        last_run = row["last_run"]

        # si erreur, on stop
        if status == "error":
            return

        # ✅ mode fiable: on attend un changement de last_run
        if last_run_before is not None:
            if last_run is not None and str(last_run) != str(last_run_before):
                return
        else:
            # fallback ancien comportement
            if status in ("idle", "error", "disabled"):
                return

        if time.time() - start > timeout:
            raise TimeoutError(f"Timeout waiting for task '{task_name}' to complete")

        time.sleep(poll_interval)

def run_task_sequence(task_names):
    """
    Ajoute la séquence à une file d'attente.
    Un worker unique exécutera les séquences une par une.
    """
    global sequence_thread_running

    logger.info(f"[QUEUE] Sequence added: {task_names}")

    with sequence_lock:
        sequence_queue.append(task_names)

        # Si aucun worker ne tourne, on le démarre
        if not sequence_thread_running:
            sequence_thread_running = True
            logger.info("[QUEUE] starting Sequence worker")
            threading.Thread(target=_sequence_worker, daemon=True).start()

def enqueue_server_discovery_sequence(server_type: str):
    """
    Planifie la séquence de découverte/sync après création d'un serveur.
    """
    server_type = (server_type or "").strip().lower()

    if server_type == "plex":
        run_task_sequence(["check_servers", "sync_plex"])
        return True

    if server_type == "jellyfin":
        run_task_sequence(["check_servers", "sync_jellyfin"])
        return True

    run_task_sequence(["check_servers"])
    return True

def _sequence_worker():
    """
    Worker chargé de vider la file d'attente, dans l'ordre FIFO.
    Toujours UNE SEULE séquence en cours.
    """
    global sequence_thread_running

    logger.info("[QUEUE] Sequence worker started")

    while True:
        with sequence_lock:
            if not sequence_queue:
                logger.info("[QUEUE] empty queue → worker stopping")
                sequence_thread_running = False
                return

            tasks = sequence_queue.pop(0)

        logger.info(f"[QUEUE] Executing new sequence : {tasks}")

        # Exécute la séquence (bloquant)
        try:
            _run_task_sequence_internal(tasks)
            logger.info(f"[QUEUE] Sequence ended : {tasks}")
        except Exception as e:
            logger.error(f"[QUEUE] Erreur while running sequence {tasks}: {e}")



def _run_task_sequence_internal(task_names):
    """
    Exécution SÉQUENTIELLE et BLOQUANTE d'une séquence.
    IMPORTANT: on n'ignore jamais une séquence.
    Le worker de séquence exécute déjà en FIFO.
    """
    logger.info(f"Sequence start : {task_names}")

    for name in task_names:
        logger.info(f"[SEQ] starting task : {name}")

        row = db.query_one(
            "SELECT id FROM tasks WHERE name=?",
            (name,)
        )
        if not row:
            logger.error(f"[SEQ] Task unknown: {name}")
            continue

        task_id = row["id"]

        # Capture last_run avant enqueue (permet de détecter 1 exécution)
        before = db.query_one("SELECT last_run FROM tasks WHERE id=?", (task_id,))
        last_run_before = before["last_run"] if before else None

        enqueued = enqueue_task(task_id)
        if not enqueued:
            logger.warning(f"[SEQ] Task not enqueued, skipping wait: {name}")
            continue

        # Attend une exécution réelle (même si la tâche reste 'queued' après)
        wait_for_task_completion(name, last_run_before=last_run_before, timeout=1800)

    logger.info(f"Sequence ended : {task_names}")
    return True

def auto_enable_monitoring_tasks():
    """
    Active/désactive les tâches de monitoring automatiquement :
    - ON si au moins 1 serveur (plex ou jellyfin) est UP
    - OFF sinon
    """
    up_count = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM servers
        WHERE LOWER(status) = 'up'
        """
    )["cnt"]

    should_enable = 1 if up_count > 0 else 0

    set_tasks_enabled_by_names_for_auto_mode(
        ["monitor_collect_sessions", "monitor_enqueue_refresh", "media_jobs_worker"],
        should_enable,
    )


def auto_enable_sync_tasks():
    plex_count = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM servers
        WHERE type = 'plex'
          AND LOWER(status) = 'up'
        """
    )["cnt"]

    row_sync_plex = db.query_one(
        "SELECT id FROM tasks WHERE name = 'sync_plex'"
    )
    if row_sync_plex:
        set_task_enabled_for_auto_mode(
            int(row_sync_plex["id"]),
            1 if plex_count > 0 else 0
        )

    jellyfin_count = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM servers
        WHERE type = 'jellyfin'
          AND LOWER(status) = 'up'
        """
    )["cnt"]

    row_sync_jellyfin = db.query_one(
        "SELECT id FROM tasks WHERE name = 'sync_jellyfin'"
    )
    if row_sync_jellyfin:
        set_task_enabled_for_auto_mode(
            int(row_sync_jellyfin["id"]),
            1 if jellyfin_count > 0 else 0
        )


def auto_enable_plex_jobs_worker():
    """
    Active/désactive apply_plex_access_updates automatiquement :
    - ON si au moins 1 serveur Plex UP OU si des media_jobs Plex non traités existent
    - OFF sinon
    """
    plex_up = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM servers
        WHERE type = 'plex'
          AND LOWER(status) = 'up'
        """
    )["cnt"]

    pending_plex_jobs = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM media_jobs mj
        JOIN servers s ON s.id = mj.server_id
        WHERE mj.processed = 0
          AND s.type = 'plex'
        """
    )["cnt"]

    should_enable = 1 if (plex_up > 0 or pending_plex_jobs > 0) else 0

    row_task = db.query_one(
        "SELECT id FROM tasks WHERE name = 'apply_plex_access_updates'"
    )
    if row_task:
        set_task_enabled_for_auto_mode(int(row_task["id"]), should_enable)

def auto_enable_jellyfin_jobs_worker():
    """
    Active/désactive apply_jellyfin_access_updates automatiquement :
    - ON si au moins 1 serveur Jellyfin UP OU si des media_jobs Jellyfin non traités existent
    - OFF sinon
    """

    jellyfin_up = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM servers
        WHERE type = 'jellyfin'
          AND LOWER(status) = 'up'
        """
    )["cnt"]

    # On compte UNIQUEMENT les jobs liés à un serveur Jellyfin
    pending_jellyfin_jobs = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM media_jobs mj
        JOIN servers s ON s.id = mj.server_id
        WHERE mj.processed = 0
          AND s.type = 'jellyfin'
        """
    )["cnt"]

    should_enable = 1 if (jellyfin_up > 0 or pending_jellyfin_jobs > 0) else 0

    row_task = db.query_one(
        "SELECT id FROM tasks WHERE name = 'apply_jellyfin_access_updates'"
    )
    if row_task:
        set_task_enabled_for_auto_mode(int(row_task["id"]), should_enable)

def auto_enable_stream_enforcer():
    """
    Active stream_enforcer automatiquement si au moins 1 policy est activée.
    Ne désactive PAS automatiquement (on respecte un éventuel choix admin).
    """
    try:
        enabled_policies = db.query_one("""
            SELECT COUNT(*) AS cnt
            FROM stream_policies
            WHERE is_enabled = 1
        """)["cnt"]

        if enabled_policies > 0:
            row_task = db.query_one(
                "SELECT id FROM tasks WHERE name = 'stream_enforcer'"
            )
            if row_task:
                set_task_enabled_for_auto_mode(int(row_task["id"]), 1)
    except Exception as e:
        logger.warning(f"auto_enable_stream_enforcer failed: {e}", exc_info=True)

def run_auto_enable_pass():
    """
    Lance tout le passage d'auto-enable/auto-disable des tâches dépendantes.
    Centralisé ici pour éviter d'avoir la même logique recopiée
    dans start_scheduler() et dans scheduler_loop().
    """
    try:
        auto_enable_sync_tasks()
    except Exception as e:
        logger.warning(
            f"Erreur auto-enable sync tasks: {e}",
            exc_info=True
        )

    try:
        auto_enable_monitoring_tasks()
    except Exception as e:
        logger.warning(
            f"Erreur auto-enable monitoring tasks: {e}",
            exc_info=True
        )

    try:
        auto_enable_stream_enforcer()
    except Exception as e:
        logger.warning(
            f"Erreur auto-enable stream_enforcer: {e}",
            exc_info=True
        )

    try:
        auto_enable_plex_jobs_worker()
    except Exception as e:
        logger.warning(
            f"Erreur auto-enable apply_plex_access_updates: {e}",
            exc_info=True
        )

    try:
        auto_enable_jellyfin_jobs_worker()
    except Exception as e:
        logger.warning(
            f"Erreur auto-enable apply_jellyfin_access_updates: {e}",
            exc_info=True
        )

def _recover_scheduler_state_at_boot():
    """
    Répare l'état des tâches au démarrage du scheduler.
    Évite de laisser des tâches coincées après crash/restart.

    Important :
    - on répare les états instables `running` / `queued`
    - on conserve `error` tel quel pour ne pas casser la logique de retry
    """
    try:
        db.execute(
            """
            UPDATE tasks
            SET status = CASE
                WHEN enabled = 0 THEN status
                WHEN queued_count > 0 THEN 'queued'
                ELSE 'idle'
            END,
            updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('running', 'queued', 'idle')
            """
        )
        logger.info("Recovery tasks: reset running/queued states OK")
        _kick_worker_if_needed()
    except Exception as e:
        logger.warning(f"Recovery tasks failed: {e}", exc_info=True)

def _run_scheduler_tick(now):
    """
    Exécute un tick complet du scheduler cron :
    - auto-enable / auto-disable des tâches dépendantes
    - chargement des tâches actives
    - calcul des prochains runs
    - enqueue des tâches dues

    Retourne True si le tick s'est déroulé normalement,
    False si on doit simplement attendre le tick suivant.
    """
    # -------------------------------------------------
    # 0) Auto-enable / disable des tâches dépendantes
    # -------------------------------------------------
    run_auto_enable_pass()

    # -------------------------------------------------
    # 1) Charger les tâches actives
    # -------------------------------------------------
    try:
        rows = db.query(
            """
            SELECT
                id, name, schedule, enabled, last_run, next_run, status,
                retry_count, max_retries, next_retry_at
            FROM tasks
            WHERE enabled = 1
            """
        )
    except Exception as e:
        logger.error(f"Scheduler error (load tasks): {e}", exc_info=True)
        return False

    # -------------------------------------------------
    # 2) Planification (CRON → enqueue)
    # -------------------------------------------------
    for row in rows:
        task_id = row["id"]
        name = row["name"]
        schedule = row["schedule"]
        last_run = row["last_run"]
        status = row["status"]
        retry_count = int(row["retry_count"] or 0)
        max_retries = int(row["max_retries"] or 0)
        next_retry_at_raw = row["next_retry_at"]

        next_retry_at = None
        if next_retry_at_raw:
            try:
                next_retry_at = datetime.fromisoformat(str(next_retry_at_raw))
            except Exception:
                next_retry_at = None

        if status == "error" and next_retry_at and retry_count < max_retries:
            if next_retry_at <= now:
                logger.info(f"Retry due for task: {name}")

                enqueued = enqueue_task(task_id)
                if enqueued:
                    try:
                        db.execute(
                            "UPDATE tasks SET next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (task_id,)
                        )
                    except Exception as retry_reset_exc:
                        logger.warning(
                            f"Unable to clear next_retry_at after retry enqueue for '{name}' (id={task_id}): {retry_reset_exc}",
                            exc_info=True,
                        )
                else:
                    logger.warning(
                        f"Retry due but enqueue refused for task '{name}' (id={task_id}); keeping next_retry_at"
                    )

            continue

        if not schedule:
            continue

        # Anti-spam: si déjà en file ou en cours, on n'enfile pas plus
        queued_count = None
        try:
            qc = db.query_one("SELECT queued_count FROM tasks WHERE id = ?", (task_id,))
            queued_count = int(qc["queued_count"]) if qc else 0
        except Exception:
            queued_count = 0

        if status in ("running", "queued") or (queued_count and queued_count > 0):
            continue

        # ---------------------------
        # Calcul du prochain run
        # ---------------------------
        next_run = row["next_run"]
        next_exec = None

        if next_run:
            try:
                next_exec = datetime.fromisoformat(str(next_run))
            except Exception:
                next_exec = None

        if next_exec is None:
            try:
                base = datetime.fromisoformat(last_run) if last_run else now
            except Exception:
                base = now

            next_exec = croniter(schedule, base).get_next(datetime)

            try:
                db.execute(
                    "UPDATE tasks SET next_run = ? WHERE id = ?",
                    (next_exec, task_id)
                )
            except Exception as e:
                if "locked" in str(e).lower():
                    logger.warning(
                        f"DB locked during count next_run for '{name}'"
                    )
                    continue
                raise

        # Première exécution forcée (UNE SEULE FOIS)
        if last_run is None:
            # si déjà planifiée dans le futur, on ne spam pas
            if next_exec and next_exec > now:
                continue

            logger.info(f"First forced execution (one-shot): {name}")

            enqueued = enqueue_task(task_id)
            if not enqueued:
                logger.warning(
                    f"Bootstrap execution enqueue refused for '{name}' (id={task_id}); keeping state unchanged"
                )
                continue

            try:
                next_future = croniter(schedule, now).get_next(datetime)
                db.execute(
                    "UPDATE tasks SET next_run = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (next_future, task_id),
                )
            except Exception as bootstrap_next_exc:
                logger.warning(
                    f"Unable to set bootstrap next_run for '{name}' (id={task_id}): {bootstrap_next_exc}",
                    exc_info=True,
                )

            # IMPORTANT: on marque un last_run "bootstrap" seulement si l'enqueue a réussi
            try:
                db.execute(
                    "UPDATE tasks SET last_run = datetime('now'), updated_at = CURRENT_TIMESTAMP WHERE id = ? AND last_run IS NULL",
                    (task_id,),
                )
            except Exception as bootstrap_last_run_exc:
                logger.warning(
                    f"Unable to mark bootstrap last_run for '{name}' (id={task_id}): {bootstrap_last_run_exc}",
                    exc_info=True,
                )

            continue

        # Exécution planifiée (rattrapage 1x, sans catch-up)
        if next_exec <= now:
            logger.info(f"Scheduled task due (late): {name}")

            enqueued = enqueue_task(task_id)
            if not enqueued:
                logger.warning(
                    f"Scheduled execution enqueue refused for '{name}' (id={task_id}); keeping next_run unchanged"
                )
                continue

            # IMPORTANT: on décale next_run dans le futur seulement si l'enqueue a réussi
            try:
                next_future = croniter(schedule, now).get_next(datetime)
                db.execute(
                    "UPDATE tasks SET next_run = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (next_future, task_id),
                )
            except Exception as e:
                # si DB locked, on évite de spammer: la tâche reste queueée de toute façon
                if "locked" in str(e).lower():
                    logger.warning(f"DB locked while updating next_run for '{name}' after enqueue")
                    continue
                raise

    return True

# -------------------------------------------------------------------
# Scheduler cron
# -------------------------------------------------------------------
def scheduler_loop():
    logger.info("VODUM scheduler started…")

    # RECOVERY AU BOOT : évite les tasks bloquées après crash/restart
    _recover_scheduler_state_at_boot()

    while True:
        if not _cron_jobs_enabled():
            # Cron OFF => don't auto-enable or schedule anything
            time.sleep(30)
            continue

        now = datetime.now()
        _kick_worker_if_needed()

        try:
            _run_scheduler_tick(now)
        except Exception as e:
            logger.error(f"Error scheduler (global): {e}", exc_info=True)

        time.sleep(30)




# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------
def start_scheduler():
    """
    Démarre :
    - le watchdog (récupération des tâches bloquées)
    - l'auto-enable des tâches dépendantes au démarrage
    - le scheduler principal

    Cette fonction est idempotente :
    si elle est appelée plusieurs fois, un seul scheduler/watchdog est lancé.
    """
    global scheduler_started

    with scheduler_start_lock:
        if scheduler_started:
            logger.info("start_scheduler() ignored: scheduler already started")
            return

        scheduler_started = True

    logger.info("starting VODUM scheduler")

    # -------------------------------------------------
    # 1) Démarrage du WATCHDOG
    # -------------------------------------------------
    watchdog_thread = threading.Thread(
        target=_watchdog_loop,
        name="vodum-watchdog",
        daemon=True
    )
    watchdog_thread.start()

    logger.info("Watchdog started")

    # -------------------------------------------------
    # 2) Auto-enable / disable des tâches dépendantes au boot
    # -------------------------------------------------
    try:
        if _cron_jobs_enabled():
            run_auto_enable_pass()
            logger.info("Task auto-enable pass run at startup")
        else:
            logger.info("Cron disabled (global); skipping auto-enable at startup")

    except Exception as e:
        logger.error(
            f"task auto-enable pass at startup failed: {e}",
            exc_info=True
        )

    # -------------------------------------------------
    # 3) Démarrage du SCHEDULER principal
    # -------------------------------------------------
    scheduler_thread = threading.Thread(
        target=scheduler_loop,
        name="vodum-scheduler",
        daemon=True
    )
    scheduler_thread.start()

    logger.info("Scheduler started")
