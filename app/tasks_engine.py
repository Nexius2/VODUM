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
        logger.error(f"Tâche inconnue : {task_name}")
        return False

    if not row["enabled"]:
        logger.warning(f"Tâche désactivée : {task_name}")
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
        logger.info(f"Tâche {task_id} ignorée (disabled)")
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
                    f"[WORKER] Erreur exécution task {row['id']}",
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
        logger.error(f"TASK {task_id} introuvable.")
        task_logs(task_id, "error", "Tâche introuvable en base")
        return

    name = row["name"]
    schedule = row["schedule"]
    module_name = f"tasks.{name}"

    logger.info(f"Lancement tâche '{name}' (id={task_id})")
    task_logs(task_id, "start", f"Lancement tâche '{name}'")

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
        msg = f"Impossible de charger {module_name}: {e}"
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
        logger.debug(f"Appel run() pour tâche '{name}'")

        # 🔒 APPEL UNIFORME — règle officielle
        run_func(task_id, db)

        duration = time.time() - start_time
        if duration > max_duration:
            raise TimeoutError(
                f"Tâche {name} trop longue ({int(duration)}s > {max_duration}s)"
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

        logger.info(f"Tâche '{name}' terminée avec succès.")
        task_logs(task_id, "success", f"Tâche '{name}' terminée avec succès")

        # -------------------------------------------------
        # Post-traitement check_servers
        # -------------------------------------------------
        if name == "check_servers":
            logger.info("Réévaluation auto des tâches sync après check_servers")
            task_logs(task_id, "info", "Réévaluation auto des tâches sync")

            try:
                auto_enable_sync_tasks()
            except Exception as e:
                logger.error(f"Erreur réévaluation sync: {e}", exc_info=True)
                task_logs(task_id, "warning", f"Réévaluation sync a échoué: {e}")

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

                logger.info(f"Prochain run '{name}' → {next_exec}")
                task_logs(task_id, "info", f"Prochain run '{name}' → {next_exec}")
            except Exception as e:
                logger.error(f"Erreur cron après exécution: {e}")
                task_logs(task_id, "warning", f"Erreur cron après exécution: {e}")

    except Exception as e:
        msg = f"Erreur pendant l'exécution de {name}: {e}"
        logger.error(msg, exc_info=True)
        task_logs(task_id, "error", msg)

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


    except Exception as e:
        msg = f"Erreur pendant l'exécution de {name}: {e}"
        logger.error(msg, exc_info=True)
        task_logs(task_id, "error", msg)

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
                    f"[FAILSAFE] Tâche {task_id} corrigée (restée en RUNNING)"
                )

        except Exception as e:
            logger.error(
                f"[FAILSAFE] Impossible de corriger la tâche {task_id}: {e}"
            )
            task_logs(task_id, "warning", f"Failsafe final a échoué: {e}")










def wait_for_task_completion(task_name, poll_interval=10):
    """
    Attend qu'une tâche donnée soit idle ou error.
    """
    while True:
        row = db.query_one(
            "SELECT status FROM tasks WHERE name=?",
            (task_name,)
        )


        if not row:
            return  # tâche inconnue = considérer comme terminée
            
        status = row["status"]

        if status in ("idle", "error"):
            return
        time.sleep(poll_interval)

def run_task_sequence(task_names):
    """
    Ajoute la séquence à une file d'attente.
    Un worker unique exécutera les séquences une par une.
    """
    global sequence_thread_running

    logger.info(f"[QUEUE] Séquence ajoutée : {task_names}")

    with queue_lock:
        sequence_queue.append(task_names)

        # Si aucun worker ne tourne, on le démarre
        if not sequence_thread_running:
            sequence_thread_running = True
            logger.info("[QUEUE] Démarrage du worker de séquences")
            threading.Thread(target=_sequence_worker, daemon=True).start()


def _sequence_worker():
    """
    Worker chargé de vider la file d'attente, dans l'ordre FIFO.
    Toujours UNE SEULE séquence en cours.
    """
    global sequence_thread_running

    logger.info("[QUEUE] Worker de séquence démarré")

    while True:
        with queue_lock:
            if not sequence_queue:
                logger.info("[QUEUE] File vide → arrêt du worker")
                sequence_thread_running = False
                return

            tasks = sequence_queue.pop(0)

        logger.info(f"[QUEUE] Exécution d'une nouvelle séquence : {tasks}")

        # Exécute la séquence (bloquant)
        try:
            _run_task_sequence_internal(tasks)
            logger.info(f"[QUEUE] Séquence terminée : {tasks}")
        except Exception as e:
            logger.error(f"[QUEUE] Erreur lors de l'exécution de la séquence {tasks}: {e}")



def _run_task_sequence_internal(task_names):
    """
    Version interne : exécution SÉQUENTIELLE et BLOQUANTE
    (dans un thread dédié, donc sans bloquer Flask).
    """
    if not sequence_lock.acquire(blocking=False):
        logger.warning("Une séquence est déjà en cours → nouvelle séquence ignorée.")
        return False

    logger.info(f"Début séquence : {task_names}")

    try:
        for name in task_names:
            logger.info(f"[SEQ] Lancement de la tâche : {name}")

            row = db.query_one(
                "SELECT id FROM tasks WHERE name=?",
                (name,)
            )


            if not row:
                logger.error(f"[SEQ] Tâche inconnue : {name}")
                continue

            task_id = row["id"]

            # Lancer la tâche asynchrone
            enqueue_task(task_id)


            # Attendre que la tâche soit terminée
            wait_for_task_completion(name)

        logger.info("Séquence terminée.")
        return True

    finally:
        sequence_lock.release()


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





# -------------------------------------------------------------------
# Scheduler cron
# -------------------------------------------------------------------
def scheduler_loop():
    logger.info("Scheduler VODUM démarré…")

    while True:
        now = datetime.now()

        try:
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
                logger.error(f"Erreur scheduler (load tasks): {e}", exc_info=True)
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
                                f"DB locked lors calcul next_run pour '{name}'"
                            )
                            continue
                        raise

                # 🔑 Première exécution forcée
                if last_run is None:
                    logger.info(f"Première exécution forcée : {name}")
                    enqueue_task(task_id)
                    continue

                # 🔑 Exécution planifiée
                if next_exec <= now:
                    logger.info(f"Tâche programmée/en retard : {name}")
                    enqueue_task(task_id)

        except Exception as e:
            logger.error(f"Erreur scheduler (global): {e}", exc_info=True)

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

    logger.info("Démarrage du scheduler VODUM")

    # -------------------------------------------------
    # 1) Démarrage du WATCHDOG
    # -------------------------------------------------
    watchdog_thread = threading.Thread(
        target=_watchdog_loop,
        name="vodum-watchdog",
        daemon=True
    )
    watchdog_thread.start()

    logger.info("Watchdog démarré")

    # -------------------------------------------------
    # 2) Auto-enable / disable des tâches de sync au boot
    # -------------------------------------------------
    try:


        auto_enable_sync_tasks()



        logger.info("Auto-enable des tâches de sync effectué au démarrage")

    except Exception as e:
        logger.error(
            f"Auto-enable sync tasks au démarrage échoué: {e}",
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

    logger.info("Scheduler lancé")



