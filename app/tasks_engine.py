import threading
import time
import traceback
import importlib
from datetime import datetime
from croniter import croniter
from db_manager import DBManager



# 🔥 AJOUT : logger TXT
from logging_utils import get_logger
logger = get_logger("tasks_engine")

# -----------------------------------------
# SEQUENCE DE TÂCHES (séquentiel + verrou)
# -----------------------------------------
sequence_lock = threading.Lock()
# ---------------------------
# QUEUE DES SÉQUENCES
# ---------------------------
sequence_queue = []
sequence_thread_running = False

task_queue = []
queue_lock = threading.Lock()
worker_running = False


db = DBManager()


# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------


TASK_MAX_DURATION = {
    "sync_plex": 60 * 60,       # 1h
    "sync_jellyfin": 30 * 60,   # 30 min
}
DEFAULT_TASK_MAX_DURATION = 30 * 60


# -------------------------------------------------------------------
# Compatibilité avec app.py (ne rien changer)
# -------------------------------------------------------------------






def run_task_by_name(task_name: str):
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



def enqueue_task(task_id: int):

    row = db.query_one(
        "SELECT enabled FROM tasks WHERE id = ?",
        (task_id,)
    )
    if not row or not row["enabled"]:
        logger.info(f"Task {task_id} ignored (disabled)")
        return


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

    # 🔑 Démarrage du worker SI nécessaire
    with queue_lock:
        if not worker_running:
            worker_running = True
            threading.Thread(
                target=_task_worker,
                name="vodum-task-worker",
                daemon=True
            ).start()




def _task_worker():
    global worker_running

    try:
        while True:
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

            if not row:
                worker_running = False
                return

            try:
                run_task(row["id"])
            except Exception as e:
                logger.error(
                    f"[WORKER] Error running task {row['id']}",
                    exc_info=True
                )

    finally:
        # 🔐 GARANTIE : le worker se libère toujours
        worker_running = False




# -------------------------------------------------------------------
# Exécution d'une tâche
# -------------------------------------------------------------------
def run_task(task_id: int):
    row = db.query_one(
        "SELECT id, name, schedule, status FROM tasks WHERE id = ?",
        (task_id,)
    )

    if not row:
        logger.error(f"TASK {task_id} missing.")
        task_logs(task_id, "error", "task missing in DB")
        return

    name = row["name"]
    schedule = row["schedule"]
    module_name = f"tasks.{name}"

    logger.info(f"Starting task '{name}' (id={task_id})")
    task_logs(task_id, "start", f"Starting task '{name}'")

    task_success = False
    start_time = time.time()
    max_duration = TASK_MAX_DURATION.get(name, DEFAULT_TASK_MAX_DURATION)

    # -------------------------------------------------
    # Passage en RUNNING (et consomme 1 élément de queue)
    # -------------------------------------------------
    try:
        db.execute(
            """
            UPDATE tasks
            SET
                status = 'running',
                last_error = NULL,
                queued_count = CASE
                    WHEN queued_count > 0 THEN queued_count - 1
                    ELSE 0
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,)
        )
    except Exception as e:
        logger.error(f"Erreur passage en running : {e}")
        task_logs(task_id, "error", f"Erreur passage en running: {e}")
        return


    # -------------------------------------------------
    # Import dynamique
    # -------------------------------------------------
    try:
        module = importlib.import_module(module_name)
        if not hasattr(module, "run"):
            raise AttributeError(f"Le module {module_name} n'expose pas run()")
        run_func = module.run
    except Exception as e:
        msg = f"Unable to load {module_name}: {e}"
        logger.error(msg)
        task_logs(task_id, "error", msg)

        try:
            db.execute(
                "UPDATE tasks SET status='error', last_error=? WHERE id=?",
                (str(e), task_id)
            )
        except Exception:
            pass

        return  # STOP NET
        
    # -------------------------------------------------
    # Exécution réelle
    # -------------------------------------------------
    try:
        logger.debug(f"Calling run() for task '{name}'")

        # 🔒 APPEL UNIFORME — règle officielle
        run_func(task_id, db)

        duration = time.time() - start_time
        if duration > max_duration:
            raise TimeoutError(
                f"Task {name} exceeded maximum duration ({int(duration)}s > {max_duration}s)"
            )

        # ---- SUCCÈS ----
        db.execute(
            """
            UPDATE tasks
            SET
                status = CASE WHEN queued_count > 0 THEN 'queued' ELSE 'idle' END,
                last_run = datetime('now'),
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,)
        )

        logger.info(f"Task '{name}' completed successfully.")
        task_logs(task_id, "success", f"Task '{name}' completed successfully")

        # -------------------------------------------------
        # Post-traitement check_servers
        # -------------------------------------------------
        if name == "check_servers":
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
            
          

        # -------------------------------------------------
        # Calcul du prochain run (sécurisé)
        # -------------------------------------------------
        if schedule:
            try:
                itr = croniter(schedule, datetime.now())
                next_exec = itr.get_next(datetime)

                db.execute(
                    "UPDATE tasks SET next_run=? WHERE id=?",
                    (next_exec, task_id)
                )

                logger.info(f"Next run '{name}' → {next_exec}")
                task_logs(task_id, "info", f"Next run '{name}' → {next_exec}")
            except Exception as e:
                logger.error(f"Cron error after execution: {e}")
                task_logs(task_id, "warning", f"Cron error after execution: {e}")

    except Exception as e:
        msg = f"Error while running {name}: {e}"
        logger.error(msg, exc_info=True)
        task_logs(task_id, "error", msg)

        try:
            db.execute(
                """
                UPDATE tasks
                SET
                    status = CASE WHEN queued_count > 0 THEN 'queued' ELSE 'error' END,
                    last_run = datetime('now'),
                    last_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(e), task_id)
            )
            # même en erreur, on calcule un next_run pour éviter les loops
            if schedule:
                try:
                    itr = croniter(schedule, datetime.now())
                    next_exec = itr.get_next(datetime)
                    db.execute("UPDATE tasks SET next_run=? WHERE id=?", (next_exec, task_id))
                except Exception:
                    pass
                
        except Exception:
            pass


#    except Exception as e:
#        msg = f"Error while running {name}: {e}"
#        logger.error(msg, exc_info=True)
#        task_logs(task_id, "error", msg)

        try:
            db.execute(
                """
                UPDATE tasks
                SET
                    status = CASE WHEN queued_count > 0 THEN 'queued' ELSE 'error' END,
                    last_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(e), task_id)
            )
        except Exception:
            pass


    finally:
        # -------------------------------------------------
        # FAILSAFE FINAL STRICT
        # -------------------------------------------------
        try:
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

    with queue_lock:
        sequence_queue.append(task_names)

        # Si aucun worker ne tourne, on le démarre
        if not sequence_thread_running:
            sequence_thread_running = True
            logger.info("[QUEUE] starting Sequence worker")
            threading.Thread(target=_sequence_worker, daemon=True).start()


def _sequence_worker():
    """
    Worker chargé de vider la file d'attente, dans l'ordre FIFO.
    Toujours UNE SEULE séquence en cours.
    """
    global sequence_thread_running

    logger.info("[QUEUE] Sequence worker started")

    while True:
        with queue_lock:
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

    # ✅ Lock BLOQUANT (au lieu de drop la séquence)
    with sequence_lock:
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

            enqueue_task(task_id)

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

    db.execute(
        """
        UPDATE tasks
        SET enabled = ?,
            status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE name IN ('monitor_collect_sessions', 'monitor_enqueue_refresh', 'media_jobs_worker')
        """,
        (should_enable, should_enable),
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

    db.execute(
        "UPDATE tasks SET enabled = ? WHERE name = 'sync_plex'",
        (1 if plex_count > 0 else 0,)
    )

    jellyfin_count = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM servers
        WHERE type = 'jellyfin'
          AND LOWER(status) = 'up'
        """
    )["cnt"]

    db.execute(
        "UPDATE tasks SET enabled = ? WHERE name = 'sync_jellyfin'",
        (1 if jellyfin_count > 0 else 0,)
    )


def auto_enable_plex_jobs_worker():
    """
    Active/désactive apply_plex_access_updates automatiquement :
    - ON si au moins 1 serveur Plex UP OU si des media_jobs non traités existent
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

    pending_jobs = db.query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM media_jobs
        WHERE processed = 0
        """
    )["cnt"]

    should_enable = 1 if (plex_up > 0 or pending_jobs > 0) else 0

    db.execute(
        """
        UPDATE tasks
        SET enabled = ?,
            status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END
        WHERE name = 'apply_plex_access_updates'
        """,
        (should_enable, should_enable),
    )



# -------------------------------------------------------------------
# Scheduler cron
# -------------------------------------------------------------------
def scheduler_loop():
    logger.info("VODUM scheduler started…")

    # ✅ RECOVERY AU BOOT : évite les tasks bloquées après crash/restart
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
            WHERE status IN ('running', 'queued', 'idle', 'error')
            """
        )
        logger.info("Recovery tasks: reset running/queued states OK")
    except Exception as e:
        logger.warning(f"Recovery tasks failed: {e}", exc_info=True)

    while True:
        now = datetime.now()

        try:
            # -------------------------------------------------
            # 0) Auto-enable / disable des tâches dépendantes
            #    (avant de charger WHERE enabled = 1)
            # -------------------------------------------------
            try:
                # --- apply_plex_access_updates : utile seulement si Plex UP ou jobs en attente
                plex_up = db.query_one(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM servers
                    WHERE type = 'plex'
                      AND LOWER(status) = 'up'
                    """
                )["cnt"]

                pending_jobs = db.query_one(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM media_jobs
                    WHERE processed = 0
                    """
                )["cnt"]

                should_enable = 1 if (plex_up > 0 or pending_jobs > 0) else 0

                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = ?,
                        status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END
                    WHERE name = 'apply_plex_access_updates'
                    """,
                    (should_enable, should_enable),
                )

            except Exception as e:
                logger.warning(
                    f"Erreur auto-enable apply_plex_access_updates: {e}",
                    exc_info=True
                )

            # -------------------------------------------------
            # 1) Charger les tâches actives
            # -------------------------------------------------
            try:
                rows = db.query(
                    """
                    SELECT id, name, schedule, enabled, last_run, next_run, status
                    FROM tasks
                    WHERE enabled = 1
                    """
                )
            except Exception as e:
                logger.error(f"Scheduler error (load tasks): {e}", exc_info=True)
                time.sleep(30)
                continue

            # -------------------------------------------------
            # 2) Planification (CRON → enqueue)
            # -------------------------------------------------
            for row in rows:
                task_id  = row["id"]
                name     = row["name"]
                schedule = row["schedule"]
                last_run = row["last_run"]
                status   = row["status"]

                if not schedule:
                    continue

                # Si la tâche est déjà running, on NE BLOQUE PAS l'enqueue
                # Le worker gère l'ordre via queued_count
                if status == "running":
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
                            "UPDATE tasks SET next_run=? WHERE id=?",
                            (next_exec, task_id)
                        )
                    except Exception as e:
                        if "locked" in str(e).lower():
                            logger.warning(
                                f"DB locked during count next_run for '{name}'"
                            )
                            continue
                        raise

                # 🔑 Première exécution forcée (UNE SEULE FOIS)
                if last_run is None:
                    # si déjà planifiée dans le futur, on ne spam pas
                    if next_exec and next_exec > now:
                        continue

                    logger.info(f"First forced execution (one-shot): {name}")
                    enqueue_task(task_id)

                    # IMPORTANT: on marque un last_run "bootstrap" pour éviter le spam à chaque tick
                    try:
                        db.execute(
                            "UPDATE tasks SET last_run=datetime('now'), updated_at=CURRENT_TIMESTAMP WHERE id=? AND last_run IS NULL",
                            (task_id,),
                        )
                    except Exception:
                        pass

                    continue


                # 🔑 Exécution planifiée
                if next_exec <= now:
                    logger.info(f"Programed task late: {name}")
                    enqueue_task(task_id)

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
    - l'auto-enable des tâches de sync au démarrage
    - le scheduler principal
    """

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
    # 2) Auto-enable / disable des tâches de sync au boot
    # -------------------------------------------------
    try:


        auto_enable_sync_tasks()
        auto_enable_monitoring_tasks



        logger.info("Sync task auto-enable run at startup")

    except Exception as e:
        logger.error(
            f"sync tasks auto-enable at startup failed: {e}",
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



