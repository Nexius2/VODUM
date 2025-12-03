# /app/tasks.py
import sqlite3
from flask import Blueprint, render_template, redirect, url_for
from datetime import datetime, UTC, timedelta
from config import DATABASE_PATH
from logger import logger
from zoneinfo import ZoneInfo
from clean_temp_files import main as clean_temp_files_main

tasks_bp = Blueprint("tasks", __name__)

TASKS = {
    "disable_expired_users": {"label": "Désactivation des utilisateurs expirés", "interval": 1440},
    "sync_users": {"label": "Synchronisation des utilisateurs Plex", "interval": 60},
    "check_servers": {"label": "Vérification des serveurs", "interval": 60},
    "send_reminders": {"label": "Envoi des rappels", "interval": 1440},
    "backup": {"label": "Sauvegarde", "interval": 1440},
    "delete_expired_users": {"label": "Suppression des utilisateurs expirés", "interval": 1440},
    "check_libraries": {"label": "Nettoyage des bibliothèques + Sync utilisateurs", "interval": 720},
    "update_user_status": {"label": "Mise à jour des statuts utilisateurs", "interval": 1440},
    "send_mail_queue": {
        "label": "Envoi des mails en attente (campagnes)",
        "interval": 60,
    },
    "clean_temp": {
        "label": "Nettoyage du dossier temporaire",
        "interval": 1440,
        "function": clean_temp_files_main
    },

    # ➕ AJOUT propre d’une tâche manuelle (pas obligatoire)
    "sync_user_libraries": {
        "label": "Synchronisation des accès Plex (user_libraries)",
        "interval": 0  # exécution uniquement manuelle
    },
}


def update_task_status(name: str, next_run: str | None = None):
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO task_status (name, last_run, next_run)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              last_run = excluded.last_run,
              next_run = excluded.next_run
        """, (name, datetime.now(UTC).isoformat(), next_run))
        conn.commit()
    finally:
        conn.close()


def get_all_tasks():
    return get_task_status()


def get_timezone():
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
    tz = get_timezone()

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, last_run, next_run FROM task_status")
    rows = cursor.fetchall()
    conn.close()

    results = []
    for name, last_run, next_run in rows:
        label = TASKS.get(name, {}).get("label", name)

        last_run_str, next_run_str = None, None
        if last_run:
            try:
                dt = datetime.fromisoformat(last_run)
                last_run_str = dt.astimezone(tz).strftime("%d/%m/%Y à %H:%M")
            except:
                last_run_str = last_run

        if next_run:
            try:
                dt = datetime.fromisoformat(next_run)
                next_run_str = dt.astimezone(tz).strftime("%d/%m/%Y à %H:%M")
            except:
                next_run_str = next_run
        else:
            interval = TASKS.get(name, {}).get("interval")
            if interval and last_run:
                try:
                    dt = datetime.fromisoformat(last_run).astimezone(tz)
                    next_run_str = (dt + timedelta(minutes=interval)).strftime("%d/%m/%Y à %H:%M")
                except:
                    next_run_str = None

        results.append({
            "name": name,
            "label": label,
            "last_run": last_run_str or "—",
            "next_run": next_run_str or "—",
        })

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
    from app import run_task
    run_task(task_name)
    return redirect(url_for("tasks.tasks"))
