import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo  # kept for backward compat in other imports
from flask import Flask, g

from config import Config
from tasks_engine import start_scheduler
from logging_utils import get_logger
from db_manager import DBManager
from core.backup import BackupConfig
from core.i18n import init_i18n

from api.subscriptions import subscriptions_api
from blueprints.users import users_bp

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, close_db
from web.filters import inject_brand_name, safe_datetime, cron_human, tz_filter


task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")


_I18N_CACHE: dict[str, dict] = {}


# -----------------------------
# AUTH RESET (local file)
# -----------------------------
RESET_FILE = os.environ.get("VODUM_RESET_FILE", "/appdata/password.reset")
RESET_MAGIC = os.environ.get("VODUM_RESET_MAGIC", "RECOVER")


def _log_ip_filter_status():
    ip_filter_enabled = (os.environ.get("VODUM_IP_FILTER") or "1").strip() not in (
        "0", "false", "False", "no", "NO"
    )


    default_allowed = "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    allowed = (os.environ.get("VODUM_ALLOWED_NETS") or default_allowed).strip()

    if ip_filter_enabled:
        security_logger.info("IP filter ENABLED | allowed_nets=%s", allowed)
    else:
        security_logger.info("IP filter DISABLED")


def startup_admin_recover_if_requested(app: Flask):
    """
    Reset LOCAL (Unraid/Docker) :
    - si RESET_FILE existe et contient RESET_MAGIC ("RECOVER")
    - au démarrage de l'app uniquement
    -> wipe admin_email + admin_password_hash
    -> supprime le fichier (one-shot)
    """
    if not os.path.exists(RESET_FILE):
        return

    try:
        with open(RESET_FILE, "r", encoding="utf-8") as f:
            marker = (f.read() or "").strip()
    except Exception:
        marker = ""

    if not marker:
        app.logger.warning(f"password.reset detected at {RESET_FILE} but file is empty. Ignoring.")
        return

    try:
        db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
        cur = db.execute(
            """
            UPDATE settings
            SET
              admin_email = NULL,
              admin_password_hash = NULL,
              auth_enabled = 1
            WHERE id = 1
            """
        )
        try:
            cur.close()
        except Exception:
            pass

        os.remove(RESET_FILE)

        app.logger.warning("Admin credentials cleared via password.reset. Please reinitialize via /setup-admin.")
    except Exception as e:
        app.logger.error(f"Startup admin recover failed: {e}")


def fromjson_safe(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except Exception:
            return None
    return None


def load_version():
    info_path = "/app/INFO"
    if not os.path.exists(info_path):
        return "dev"

    version = "dev"
    with open(info_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("VERSION="):
                version = line.split("=", 1)[1].strip()
                break
    return version


APP_VERSION = load_version()


def _reset_maintenance_on_startup(app: Flask):
    """
    If the app was left in maintenance mode after a restore,
    reset it automatically on container restart.

    Note:
    - We ONLY do this when maintenance_mode == 1 (restore flow).
    - We DO NOT enable every task blindly.
    - We re-enable only the tasks that are enabled by default in db_bootstrap.py.
    """
    try:
        db = DBManager(app.config["DATABASE"])
        settings = db.query_one("SELECT maintenance_mode FROM settings WHERE id = 1")
        if not settings:
            return

        if int(settings["maintenance_mode"] or 0) != 1:
            return

        db.execute("UPDATE settings SET maintenance_mode = 0 WHERE id = 1")

        # Re-enable only default core tasks (as in original behavior)
        core_tasks = [
            "check_servers",
            "update_user_status",
            "cleanup_backups",
            "cleanup_unfriended",
            "check_update",
        ]
        try:
            for tname in core_tasks:
                db.execute(
                    "UPDATE scheduled_tasks SET enabled = 1 WHERE name = ? AND (enabled IS NULL OR enabled = 0)",
                    (tname,),
                )
            get_logger("boot").warning(
                "Startup restore recovery: re-enabled core tasks: %s",
                ", ".join(core_tasks),
            )
        except Exception:
            get_logger("boot").exception("Startup restore recovery: failed to restore core task states")

    except Exception:
        get_logger("boot").exception("Failed to reset maintenance mode on startup")


def _resolve_asset_dir(start_dir: str, target: str) -> str:
    """
    Find a folder named `target` by looking in start_dir, then its parent.
    Works whether the repo is copied as /app/* or /app/app/* etc.
    """
    candidates = [
        os.path.join(start_dir, target),
        os.path.join(os.path.dirname(start_dir), target),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    # fallback: relative name (Flask may resolve it)
    return target

def create_app():
    # Ensure templates/static/lang are loaded correctly regardless of whether the code is mounted as
    # /app/app.py or /app/app/app.py (Docker COPY layouts vary).
    base_dir = os.path.dirname(os.path.abspath(__file__))

    template_dir = _resolve_asset_dir(base_dir, "templates")
    static_dir = _resolve_asset_dir(base_dir, "static")
    lang_dir = _resolve_asset_dir(base_dir, "lang")

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

    # Absolute path to lang/
    app.config["LANG_DIR"] = lang_dir

    # Filters / globals
    app.jinja_env.filters["fromjson"] = fromjson_safe

    @app.before_request
    def inject_version():
        g.app_version = APP_VERSION

        # Update badge (sans BDD) -> lit /appdata/update_status.json
        g.update_available = False
        try:
            status_path = "/appdata/update_status.json"
            if os.path.exists(status_path):
                with open(status_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f) or {}
                g.update_available = bool(data.get("update_available"))
        except Exception:
            g.update_available = False

    app.config.from_object(Config)

    # RESET au démarrage (avant routes / scheduler)
    startup_admin_recover_if_requested(app)

    # Backup dir
    app.config.setdefault("BACKUP_DIR", os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups"))

    # i18n (requires DB access)
    init_i18n(app, get_db)

    # Context processor + template filters
    app.context_processor(inject_brand_name)
    app.template_filter("safe_datetime")(safe_datetime)
    app.template_filter("cron_human")(cron_human)
    app.template_filter("tz")(tz_filter)

    # DB teardown
    app.teardown_appcontext(close_db)

    # Blueprints
    app.register_blueprint(subscriptions_api)
    app.register_blueprint(users_bp)

    # Routes (split from former gigantic app.py)
    from routes.dashboard import register as register_dashboard
    from routes.monitoring_overview import register as register_monitoring_overview
    from routes.monitoring_user import register as register_monitoring_user
    from routes.monitoring_api import register as register_monitoring_api
    from routes.tasks_api import register as register_tasks_api
    from routes.users_list import register as register_users_list
    from routes.users_detail import register as register_users_detail
    from routes.users_actions import register as register_users_actions
    from routes.servers import register as register_servers
    from routes.subscriptions_page import register as register_subscriptions_page
    from routes.tasks import register as register_tasks
    from routes.mailing_pages import register as register_mailing_pages
    from routes.mailing_templates import register as register_mailing_templates
    from routes.discord import register as register_discord
    from routes.backup import register as register_backup
    from routes.auth import register as register_auth
    from routes.settings import register as register_settings
    from routes.logs import register as register_logs
    from routes.about import register as register_about

    register_dashboard(app)
    register_monitoring_overview(app)
    register_monitoring_user(app)
    register_monitoring_api(app)
    register_tasks_api(app)
    register_users_list(app)
    register_users_detail(app)
    register_users_actions(app)
    register_servers(app)
    register_subscriptions_page(app)
    register_tasks(app)
    register_mailing_pages(app)
    register_mailing_templates(app)
    register_discord(app)
    register_backup(app)
    register_auth(app)
    register_settings(app)
    register_logs(app)
    register_about(app)

    # Expose helpers pour d’éventuels scripts internes
    app.get_db = get_db
    app.table_exists = table_exists
    app.scheduler_db_provider = lambda: DBManager(app.config["DATABASE"])

    _reset_maintenance_on_startup(app)

    return app


app = create_app()

# ✅ Evite double démarrage du scheduler en mode debug (reloader)
if (not app.debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    with app.app_context():
        start_scheduler()


if __name__ == "__main__":
    _log_ip_filter_status()
    app.run(host="0.0.0.0", port=5000, use_reloader=False)
