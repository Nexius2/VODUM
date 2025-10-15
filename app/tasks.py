# /app/tasks.py
import sqlite3
from flask import Blueprint, render_template, redirect, url_for
from datetime import datetime, UTC
from config import DATABASE_PATH
from logger import logger
from zoneinfo import ZoneInfo  # Python 3.9+
from clean_temp_files import main as clean_temp_files_main


tasks_bp = Blueprint("tasks", __name__)

# Liste des tâches connues (nom technique → libellé lisible + fréquence en minutes)
TASKS = {
    "disable_expired_users": {"label": "Désactivation des utilisateurs expirés", "interval": 1440},   # 1/jour
    "sync_users": {"label": "Synchronisation des utilisateurs Plex", "interval": 60},                # 1/heure
    "check_servers": {"label": "Vérification des serveurs", "interval": 60},                         # 1/heure
    "send_reminders": {"label": "Envoi des rappels", "interval": 1440},                              # 1/jour
    "backup": {"label": "Sauvegarde", "interval": 1440},                                             # 1/jour
    "delete_expired_users": {"label": "Suppression des utilisateurs expirés", "interval": 1440},     # 1/jour
    "check_libraries": {"label": "Nettoyage des bibliothèques", "interval": 720},                    # 2/jour
    "update_user_status": {"label": "Mise à jour des statuts utilisateurs", "interval": 1440},       # 1/jour
    "send_mail_queue": {
        "label": "Envoi des mails en attente (campagnes)",
        "interval": 60,  # toutes les heures (adaptable)
    },
    "clean_temp": {
        "label": "Nettoyage du dossier temporaire",
        "interval": 1440,  # 1 fois par jour
        "function": clean_temp_files_main
    },

}


def update_task_status(name: str, next_run: str | None = None):
    """
    Met à jour la ligne de la tâche dans task_status.
    - name: nom de la tâche (ex: 'check_servers', 'disable_expired_users')
    - next_run: ISO 8601 ou None
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO task_status (name, last_run, next_run)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              last_run = excluded.last_run,
              next_run = excluded.next_run
            """,
            (name, datetime.now(UTC).isoformat(), next_run),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_tasks():
    """Retourne toutes les tâches connues avec leur état (compatibilité avec app.py)."""
    return get_task_status()


def get_timezone():
    """Retourne le fuseau horaire configuré dans la BDD (fallback = UTC)."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT timezone FROM settings LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        try:
            return ZoneInfo(row[0])
        except Exception:
            logger.warning(f"⚠️ Fuseau horaire invalide en BDD : {row[0]}, fallback UTC")
    return ZoneInfo("UTC")


def get_task_status():
    """Retourne la liste des tâches avec leurs dernières exécutions et prochaines exécutions."""
    tz = get_timezone()

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, last_run, next_run FROM task_status")
    rows = cursor.fetchall()
    conn.close()

    results = []
    for name, last_run, next_run in rows:
        label = TASKS.get(name, {}).get("label", name)

        # Conversion fuseau horaire
        last_run_str, next_run_str = None, None
        if last_run:
            try:
                dt = datetime.fromisoformat(last_run)
                last_run_str = dt.astimezone(tz).strftime("%d/%m/%Y à %H:%M")
            except Exception:
                last_run_str = last_run

        if next_run:
            try:
                dt = datetime.fromisoformat(next_run)
                next_run_str = dt.astimezone(tz).strftime("%d/%m/%Y à %H:%M")
            except Exception:
                next_run_str = next_run
        else:
            # Si pas de next_run en BDD → calcul automatique
            interval = TASKS.get(name, {}).get("interval")
            if interval and last_run:
                try:
                    dt = datetime.fromisoformat(last_run).astimezone(tz)
                    next_run_str = (dt + timedelta(minutes=interval)).strftime("%d/%m/%Y à %H:%M")
                except Exception:
                    next_run_str = None

        results.append({
            "name": name,
            "label": label,
            "last_run": last_run_str or "—",
            "next_run": next_run_str or "—",
        })

    # Ajouter les tâches définies dans TASKS mais absentes de la BDD
    existing = {row[0] for row in rows}
    for name, cfg in TASKS.items():
        if name not in existing:
            results.append({
                "name": name,
                "label": cfg["label"],
                "last_run": "—",
                "next_run": "—",
            })

    return results

@tasks_bp.route("/tasks")
def tasks():
    return render_template("tasks.html", tasks=get_task_status())

@tasks_bp.route("/run_task/<task_name>", methods=["POST"])
def run_task(task_name):
    from app import run_task  # éviter les imports circulaires
    run_task(task_name)
    return redirect(url_for("tasks.tasks"))
