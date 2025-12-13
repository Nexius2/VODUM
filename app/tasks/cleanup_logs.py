from db_utils import open_db
from tasks_engine import task_logs
from datetime import datetime

DEFAULT_RETENTION = 30  # 30 jours si non configuré

def get_retention_days():
    try:
        conn = open_db()
        cur = conn.cursor()
        cur.execute("SELECT cleanup_log_days FROM settings LIMIT 1")
        row = cur.fetchone()
        conn.close()

        if row and row[0]:
            return int(row[0])

    except Exception as e:
        task_logs(None, "error", f"[cleanup_logs] Erreur lecture settings : {e}")

    return DEFAULT_RETENTION


def run(task_id, db=None):
    retention = get_retention_days()

    try:
        conn = open_db()
        cur = conn.cursor()

        # Supprimer les logs anciens
        cur.execute(
            "DELETE FROM logs WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{retention} days",)
        )
        deleted_logs = cur.rowcount

        conn.commit()
        conn.close()

        msg = f"[cleanup_logs] {deleted_logs} logs supprimés (> {retention} jours)."
        print(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        err = f"[cleanup_logs] Erreur pendant le nettoyage : {e}"
        print(err)
        task_logs(task_id, "error", err)
