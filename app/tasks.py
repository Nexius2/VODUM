import json
from datetime import datetime
from plexapi.server import PlexServer

from app import get_db
from app.sync_plex import sync_users_from_plex, sync_libraries_from_plex


# ==============
#  TABLE HELPERS
# ==============

def create_task(task_type, params=None):
    db = get_db()
    db.execute("""
        INSERT INTO tasks (task_type, params, status, progress, created_at)
        VALUES (?, ?, 'queued', 0, datetime('now'))
    """, (task_type, json.dumps(params)))
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def update_task(task_id, status=None, progress=None, message=None):
    db = get_db()
    if status:
        db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    if progress is not None:
        db.execute("UPDATE tasks SET progress=? WHERE id=?", (progress, task_id))
    if message:
        db.execute("UPDATE tasks SET message=? WHERE id=?", (message, task_id))

    db.execute("UPDATE tasks SET last_run=datetime('now') WHERE id=?", (task_id,))
    db.commit()


# ==============
#  TASK HANDLERS
# ==============

def task_sync_server(params, task_id):
    """Synchronise un serveur Plex complet."""
    server_id = params["server_id"]

    db = get_db()
    server = db.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()

    if not server:
        update_task(task_id, "error", message="Serveur introuvable")
        return

    update_task(task_id, "running", 5, "Connexion au serveur Plex...")

    try:
        plex = PlexServer(server["url"], server["token"])
    except Exception as e:
        update_task(task_id, "error", message=f"Erreur de connexion : {e}")
        return

    # USERS
    update_task(task_id, progress=20, message="Synchronisation des utilisateurs...")
    sync_users_from_plex(plex, server_id)

    # LIBRARIES
    update_task(task_id, progress=60, message="Synchronisation des bibliothèques...")
    sync_libraries_from_plex(plex, server_id)

    update_task(task_id, status="done", progress=100, message="Terminé")


# =====================
#  TASK ROUTER
# =====================

TASK_HANDLERS = {
    "sync_server": task_sync_server,
}


def run_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    if not task:
        return False

    params = json.loads(task["params"]) if task["params"] else None
    handler = TASK_HANDLERS.get(task["task_type"])

    if not handler:
        update_task(task_id, "error", message="Type de tâche inconnu")
        return False

    try:
        handler(params, task_id)
    except Exception as e:
        update_task(task_id, "error", message=str(e))

    return True
