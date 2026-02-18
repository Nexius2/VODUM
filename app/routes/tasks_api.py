# Auto-split from app.py (keep URLs/endpoints intact)
import os
import json
import time
import re
import math
import platform
import ipaddress
import uuid
import threading
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from flask import (
    render_template, g, request, redirect, url_for, flash, session,
    Response, current_app, jsonify, make_response, abort,
)

from db_manager import DBManager
from logging_utils import get_logger, read_last_logs, read_all_logs
from tasks_engine import run_task, start_scheduler, run_task_sequence, run_task_by_name, enqueue_task
from mailing_utils import build_user_context, render_mail
from discord_utils import is_discord_ready, validate_discord_bot_token
from core.i18n import get_translator, get_available_languages
from core.backup import BackupConfig, ensure_backup_dir, create_backup_file, list_backups, restore_backup_file
from werkzeug.security import generate_password_hash, check_password_hash

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg
from web.filters import cron_human, tz_filter


task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

def register(app):
    @app.route("/api/tasks/list", methods=["GET"])
    def api_tasks_list():
        db = get_db()

        if not table_exists(db, "tasks"):
            return {"tasks": []}

        t = get_translator()

        rows = db.query(
            """
            SELECT
                id,
                name,
                description,
                schedule,
                status,
                enabled,
                last_run,
                next_run
            FROM tasks
            ORDER BY name
            """
        )

        tasks = []
        for r in rows:
            name = r["name"]
            desc = r["description"]

            # Labels comme dans tasks.html:
            # {{ t("task." ~ task.name) or task.name }}
            # {{ t("task_description." ~ task.name) or task.description or "-" }}
            name_label = t(f"task.{name}") or name
            desc_label = t(f"task_description.{name}") or (desc or "-")

            schedule = r["schedule"] or ""
            schedule_human = cron_human(schedule) if schedule else "-"

            last_run_human = tz_filter(r["last_run"]) if r["last_run"] else "-"
            next_run_human = tz_filter(r["next_run"]) if r["next_run"] else "-"

            tasks.append({
                "id": r["id"],
                "name": name,
                "description": desc,
                "schedule": schedule,
                "status": r["status"],
                "enabled": bool(r["enabled"]),
                "name_label": name_label,
                "description_label": desc_label,
                "schedule_human": schedule_human,
                "last_run_human": last_run_human,
                "next_run_human": next_run_human,
            })

        return {"tasks": tasks}




    @app.route("/api/tasks/activity", methods=["GET"])
    def api_tasks_activity():
        db = get_db()

        if not table_exists(db, "tasks"):
            return {"active": 0, "running": 0, "queued": 0}

        row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
              SUM(CASE WHEN status = 'queued'  THEN 1 ELSE 0 END) AS queued
            FROM tasks
            WHERE status IN ('running', 'queued')
            """
        )

        if row is None:
            return {"active": 0, "running": 0, "queued": 0}

        running = row["running"] or 0
        queued  = row["queued"]  or 0
        active  = running + queued

        return {
            "active": active,
            "running": running,
            "queued": queued
        }







    # -----------------------------
    # ROUTES
    # -----------------------------


