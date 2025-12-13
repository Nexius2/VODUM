import sqlite3
import threading
import time
import traceback
import importlib
from datetime import datetime, timedelta
from croniter import croniter
from db_utils import open_db

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
queue_lock = threading.Lock()


# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
DB_PATH = "/appdata/database.db"

# -------------------------------------------------------------------
# Compatibilité avec app.py (ne rien changer)
# -------------------------------------------------------------------
def set_db_provider(provider):
    return  # volontairement vide

# -------------------------------------------------------------------
# Helpers DB
# -------------------------------------------------------------------
def get_db():
    return open_db()

def safe_execute(cur, query, params=(), retries=10, delay=0.2):
    for _ in range(retries):
        try:
            return cur.execute(query, params)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                logger.warning(f"DB locked → retry in {delay}s: {e}")
                time.sleep(delay)
                continue
            raise
    raise sqlite3.OperationalError("Database locked after multiple retries")

# -------------------------------------------------------------------
# Logging DB existant (NON SUPPRIMÉ)
# -------------------------------------------------------------------
def task_logs(task_id, status, message, details=None):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()

        safe_execute(cur, "SELECT name FROM tasks WHERE id=?", (task_id,))
        row = cur.fetchone()
        task_name = row["name"] if row else f"task_{task_id}"

        level = "INFO"
        if str(status).lower() in ("error", "err", "failed", "ko"):
            level = "ERROR"
        elif str(status).lower() in ("warn", "warning"):
            level = "WARNING"

        if details is not None and not isinstance(details, str):
            try:
                import json
                details = json.dumps(details, ensure_ascii=False)
            except:
                details = str(details)

        safe_execute(
            cur,
            """
                INSERT INTO logs(level, category, message, details, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (level, f"task:{task_name}", message, details),
        )

        conn.commit()

    except Exception as e:
        logger.error(f"[LOGGER ERROR] Impossible d'écrire dans logs DB: {e}")

    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# -------------------------------------------------------------------
# Exécution d'une tâche
# -------------------------------------------------------------------
def run_task(task_id: int):
    conn = get_db()
    cur = conn.cursor()

    safe_execute(cur, "SELECT id, name, schedule FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()

    if not row:
        logger.error(f"TASK {task_id} introuvable.")
        conn.close()
        return

    name = row["name"]
    schedule = row["schedule"]
    module_name = f"tasks.{name}"

    logger.info(f"Lancement tâche '{name}' (id={task_id})")

    # Mise en running
    try:
        safe_execute(
            cur,
            "UPDATE tasks SET status='running', last_error=NULL WHERE id=?",
            (task_id,),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Erreur passage en running (lock ?) : {e}")
        conn.close()
        return

    # Import dynamique
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        msg = f"Impossible d'importer {module_name}: {e}"
        logger.error(msg)
        task_logs(task_id, "error", msg)
        traceback.print_exc()

        safe_execute(
            cur,
            "UPDATE tasks SET status='error', last_error=? WHERE id=?",
            (str(e), task_id),
        )
        conn.commit()
        conn.close()
        return

    if not hasattr(module, "run"):
        msg = f"Le module {module_name} n'expose pas run()"
        logger.error(msg)
        task_logs(task_id, "error", msg)

        safe_execute(
            cur,
            "UPDATE tasks SET status='error', last_error=? WHERE id=?",
            (msg, task_id),
        )
        conn.commit()
        conn.close()
        return

    run_func = getattr(module, "run")

    # Exécution réelle
    try:
        logger.debug(f"Appel run() pour tâche '{name}'")
        run_func(task_id, db=conn)

        # Succès
        safe_execute(
            cur,
            """
                UPDATE tasks 
                SET status='idle', last_run=datetime('now'), last_error=NULL 
                WHERE id=?
            """,
            (task_id,),
        )
        conn.commit()

        logger.info(f"Tâche '{name}' terminée avec succès.")
        task_logs(task_id, "success", f"Tâche {name} exécutée avec succès.")

        # Calcul prochain run
        if schedule:
            try:
                now = datetime.now()
                itr = croniter(schedule, now)
                next_exec = itr.get_next(datetime)

                safe_execute(
                    cur,
                    "UPDATE tasks SET next_run=? WHERE id=?",
                    (next_exec, task_id),
                )
                conn.commit()

                logger.info(f"Prochain run '{name}' → {next_exec}")

            except Exception as e:
                logger.error(f"Erreur cron après exécution: {e}")
                traceback.print_exc()

    except Exception as e:
        msg = f"Erreur pendant l'exécution de {name}: {e}"
        logger.error(msg)
        task_logs(task_id, "error", msg)
        traceback.print_exc()

        safe_execute(
            cur,
            "UPDATE tasks SET status='error', last_error=? WHERE id=?",
            (str(e), task_id),
        )
        conn.commit()

    finally:
        conn.close()


def wait_for_task_completion(task_name, poll_interval=1):
    """
    Attend qu'une tâche donnée soit idle ou error.
    """
    while True:
        conn = get_db()
        cur = conn.cursor()
        safe_execute(cur, "SELECT status FROM tasks WHERE name=?", (task_name,))
        row = cur.fetchone()
        conn.close()

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

            conn = get_db()
            cur = conn.cursor()

            # Récupération de l'ID
            safe_execute(cur, "SELECT id FROM tasks WHERE name=?", (name,))
            row = cur.fetchone()
            conn.close()

            if not row:
                logger.error(f"[SEQ] Tâche inconnue : {name}")
                continue

            task_id = row["id"]

            # Lancer la tâche asynchrone
            threading.Thread(
                target=run_task,
                args=(task_id,),
                daemon=True
            ).start()

            # Attendre que la tâche soit terminée
            wait_for_task_completion(name)

        logger.info("Séquence terminée.")
        return True

    finally:
        sequence_lock.release()



# -------------------------------------------------------------------
# Scheduler cron
# -------------------------------------------------------------------
def scheduler_loop():
    logger.info("Scheduler VODUM démarré…")

    while True:
        now = datetime.now()

        try:
            conn = get_db()
            cur = conn.cursor()

            try:
                safe_execute(
                    cur,
                    """
                        SELECT id, name, schedule, enabled, last_run, status
                        FROM tasks
                        WHERE enabled = 1
                    """
                )
                rows = cur.fetchall()
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    logger.warning("DB locked pendant SELECT tasks → retry cycle.")
                    conn.close()
                    time.sleep(30)
                    continue
                else:
                    raise

            for row in rows:
                task_id   = row["id"]
                name      = row["name"]
                schedule  = row["schedule"]
                last_run  = row["last_run"]
                status    = row["status"]

                if not schedule:
                    continue
                if status == "running":
                    continue

                try:
                    base = datetime.fromisoformat(last_run) if last_run else now
                except Exception:
                    base = now

                next_exec = croniter(schedule, base).get_next(datetime)

                try:
                    safe_execute(
                        cur,
                        "UPDATE tasks SET next_run=? WHERE id=?",
                        (next_exec, task_id),
                    )
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        logger.warning(f"DB locked lors UPDATE next_run pour '{name}'")
                        continue
                    else:
                        raise

                if next_exec <= now + timedelta(minutes=2):
                    logger.info(f"Tâche programmée/en retard : {name}")
                    threading.Thread(
                        target=run_task,
                        args=(task_id,),
                        daemon=True
                    ).start()

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Erreur scheduler: {e}")
            traceback.print_exc()

        time.sleep(30)

# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------
def start_scheduler():
    logger.info("Activation du scheduler…")
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    logger.info("Scheduler démarré.")
