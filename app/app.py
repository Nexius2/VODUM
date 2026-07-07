import os
import gzip
import json
import hmac
import secrets
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo  # kept for backward compat in other imports
from flask import Flask, g, request, session, abort
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from logging_utils import get_logger
task_logger = get_logger("app")
from db_manager import DBManager, open_sqlite_connection
from core.backup import BackupConfig
from core.i18n import init_i18n
from core.repair.plex_media_users_repair import run_repair_if_needed
from core.monitoring.plex_websocket import PlexWebsocketClient
from core.startup import StartupStep, run_startup_sequence
from core.app_paths import update_status_path
from utils.version import load_app_version

from api.subscriptions import subscriptions_api
from blueprints.users import users_bp

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, close_db
from web.filters import inject_brand_name, safe_datetime, cron_human, tz_filter, browser_datetime, utc_iso
from web.security import ip_in_networks


task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")
performance_logger = get_logger("performance")


_I18N_CACHE: dict[str, dict] = {}

class ConditionalProxyFix:
    """
    Applique ProxyFix uniquement si enabled_getter() retourne True.
    Permet d'activer/désactiver dynamiquement le trust proxy via les settings.
    """
    def __init__(self, wsgi_app, enabled_getter, trusted_networks_getter):
        self._raw_app = wsgi_app
        self._proxy_app = ProxyFix(wsgi_app, x_for=1, x_proto=1, x_host=1)
        self._enabled_getter = enabled_getter
        self._trusted_networks_getter = trusted_networks_getter

    def __call__(self, environ, start_response):
        peer_ip = environ.get("REMOTE_ADDR")
        if (
            self._enabled_getter()
            and ip_in_networks(peer_ip, self._trusted_networks_getter())
        ):
            return self._proxy_app(environ, start_response)
        return self._raw_app(environ, start_response)


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return str(raw).strip() not in ("0", "false", "False", "no", "NO")


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def _read_trust_proxy_from_db(db_path: str) -> bool:
    conn = None
    try:
        conn = open_sqlite_connection(db_path, read_only=True)
        row = conn.execute(
            "SELECT web_trust_proxy FROM settings WHERE id = 1"
        ).fetchone()

        if not row:
            return False

        return int(row["web_trust_proxy"] or 0) == 1
    except Exception:
        return False
    finally:
        if conn is not None:
            conn.close()

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

    trusted_proxies = os.environ.get(
        "VODUM_TRUSTED_PROXY_NETS",
        "127.0.0.1/32,::1/128",
    )
    security_logger.info("Trusted proxy networks | trusted_nets=%s", trusted_proxies)


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

    if marker != RESET_MAGIC:
        app.logger.warning(f"password.reset detected at {RESET_FILE} but marker is invalid. Ignoring.")
        return

    try:
        db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
        cur = db.execute(
            """
            UPDATE settings
            SET
              admin_email = NULL,
              admin_password_hash = NULL,
              admin_totp_enabled = 0,
              admin_totp_secret = NULL,
              auth_enabled = 1
            WHERE id = 1
            """
        )
        try:
            cur.close()
        except Exception as e:
            app.logger.warning(f"Unable to close startup recovery cursor: {e}", exc_info=True)

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


APP_VERSION = load_app_version(fallback="dev")


def _reset_maintenance_on_startup(app: Flask):
    """
    Si l'app a été laissée en maintenance après une restauration DB,
    on remet un état propre au démarrage.

    - maintenance_mode -> 0
    - enabled <- enabled_prev si présent
    - status recalculé proprement
    - enabled_prev vidé
    """
    try:
        db = DBManager(app.config["DATABASE"])

        settings = db.query_one("SELECT maintenance_mode FROM settings WHERE id = 1")
        if not settings:
            return

        if int(settings["maintenance_mode"] or 0) != 1:
            return

        # Leave maintenance mode
        db.execute("UPDATE settings SET maintenance_mode = 0 WHERE id = 1")

        # Restore tasks to their previous state
        db.execute(
            """
            UPDATE tasks
            SET
                enabled = CASE
                    WHEN enabled_prev IS NULL THEN enabled
                    ELSE enabled_prev
                END,
                status = CASE
                    WHEN (
                        CASE
                            WHEN enabled_prev IS NULL THEN enabled
                            ELSE enabled_prev
                        END
                    ) = 0 THEN 'disabled'
                    WHEN COALESCE(queued_count, 0) > 0 THEN 'queued'
                    ELSE 'idle'
                END,
                enabled_prev = NULL,
                updated_at = CURRENT_TIMESTAMP
            """
        )

        get_logger("boot").warning(
            "Startup restore recovery: maintenance cleared and task states restored from enabled_prev"
        )

    except Exception:
        get_logger("boot").exception("Failed to reset maintenance mode on startup")

def _run_one_shot_repair(app: Flask):
    boot_logger = get_logger("boot")
    with app.app_context():
        db = get_db()
        repair_result = run_repair_if_needed(db, app.logger)

    if repair_result and repair_result.get("status") == "done":
        boot_logger.warning(
            "[BOOT] one-shot repair executed | key=%s | stats=%s",
            repair_result.get("repair_key"),
            repair_result.get("stats"),
        )
    elif repair_result and repair_result.get("status") == "skipped":
        boot_logger.info(
            "[BOOT] one-shot repair skipped | key=%s | reason=%s",
            repair_result.get("repair_key"),
            repair_result.get("reason"),
        )
    else:
        boot_logger.info("[BOOT] one-shot repair finished with no explicit result")


def _start_plex_websocket_engine(app: Flask):
    db = DBManager(app.config["DATABASE"])
    plex_servers = db.query(
        """
        SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers
        WHERE LOWER(TRIM(type)) = 'plex'
          AND token IS NOT NULL
          AND TRIM(token) != ''
        """
    )

    for server_row in plex_servers or []:
        server = dict(server_row)
        try:
            PlexWebsocketClient(server).start()
        except Exception:
            task_logger.exception(
                "Unable to start Plex websocket for %s",
                server.get("name"),
            )


def _run_application_startup(app: Flask):
    """Declare the complete post-registration startup order in one place."""
    run_startup_sequence(
        app,
        (
            StartupStep("admin_recovery", startup_admin_recover_if_requested),
            StartupStep("maintenance_recovery", _reset_maintenance_on_startup),
            StartupStep("one_shot_repair", _run_one_shot_repair),
            StartupStep("plex_websocket_engine", _start_plex_websocket_engine, fatal=False),
        ),
    )

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
    # Ensure templates/static/translations are loaded correctly regardless of whether the code is mounted as
    # /app/app.py or /app/app/app.py (Docker COPY layouts vary).
    base_dir = os.path.dirname(os.path.abspath(__file__))

    template_dir = _resolve_asset_dir(base_dir, "templates")
    static_dir = _resolve_asset_dir(base_dir, "static")
    lang_dir = _resolve_asset_dir(base_dir, os.path.join("translations", "ui"))

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

    def _get_csrf_token() -> str:
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": _get_csrf_token()}

    @app.before_request
    def csrf_guard():
        # Protège uniquement les méthodes qui modifient l'état
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return

        # Pas utile sur ces endpoints publics / techniques
        allowed_prefixes = ("/static", "/health")
        if request.path.startswith(allowed_prefixes) or request.path in ("/favicon.ico",):
            return

        sent_token = (
            request.form.get("_csrf_token")
            or request.headers.get("X-CSRF-Token")
            or ""
        ).strip()

        session_token = (session.get("_csrf_token") or "").strip()

        if (
            not sent_token
            or not session_token
            or not hmac.compare_digest(sent_token, session_token)
        ):
            abort(403)

    # Trust proxy :
    # - priorité à la variable d'environnement si elle existe
    # - sinon fallback sur la valeur stockée en base/settings
    env_trust_proxy = _env_bool("VODUM_TRUST_PROXY")
    db_path = os.environ.get("DATABASE_PATH", "/appdata/database.db")

    if env_trust_proxy is None:
        initial_trust_proxy = _read_trust_proxy_from_db(db_path)
    else:
        initial_trust_proxy = env_trust_proxy

    app.config["TRUST_PROXY_ENABLED"] = bool(initial_trust_proxy)
    app.config["TRUSTED_PROXY_NETS"] = os.environ.get(
        "VODUM_TRUSTED_PROXY_NETS",
        "127.0.0.1/32,::1/128",
    )

    # Middleware conditionnel : lit app.config à chaque requête
    app.wsgi_app = ConditionalProxyFix(
        app.wsgi_app,
        lambda: bool(app.config.get("TRUST_PROXY_ENABLED", False)),
        lambda: str(app.config.get("TRUSTED_PROXY_NETS", "")),
    )

    # Absolute path to translations/ui. app/core/i18n.py can still read an external legacy lang/ fallback.
    app.config["LANG_DIR"] = lang_dir

    # Filters / globals
    app.jinja_env.filters["fromjson"] = fromjson_safe

    @app.before_request
    def inject_version():
        g.app_version = APP_VERSION

        # Update badge (sans BDD) -> lit le status dans le data dir configure
        g.update_available = False
        try:
            status_path = update_status_path()
            if status_path.exists():
                with status_path.open("r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f) or {}
                g.update_available = bool(data.get("update_available"))
                g.update_pending_days = int(data.get("update_pending_days") or 0)
        except Exception:
            g.update_available = False
            g.update_pending_days = 0

    app.config.from_object(Config)
    static_max_age = _env_int("VODUM_STATIC_MAX_AGE_SECONDS", 60 * 60 * 24 * 30, minimum=0)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = timedelta(seconds=max(0, static_max_age))

    # Ne pas écraser la valeur déjà calculée depuis env / DB
    app.config.setdefault("TRUST_PROXY_ENABLED", False)

    # Backup dir
    app.config.setdefault("BACKUP_DIR", os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups"))

    route_timing_enabled = _env_bool("VODUM_ROUTE_TIMING") is True
    route_timing_threshold_ms = _env_int("VODUM_ROUTE_TIMING_THRESHOLD_MS", 300, minimum=0)

    @app.before_request
    def start_route_timing():
        if route_timing_enabled:
            g.route_started_at = time.perf_counter()

    @app.after_request
    def log_slow_route(response):
        started_at = getattr(g, "route_started_at", None)
        if started_at is None:
            return response

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        if duration_ms >= route_timing_threshold_ms and not request.path.startswith("/static"):
            performance_logger.info(
                "route_timing | duration_ms=%s | status=%s | method=%s | path=%s | endpoint=%s | content_length=%s | htmx=%s",
                duration_ms,
                response.status_code,
                request.method,
                request.path,
                request.endpoint or "-",
                response.calculate_content_length() or 0,
                "1" if request.headers.get("HX-Request") else "0",
            )
        return response

    gzip_enabled = _env_bool("VODUM_HTTP_GZIP") is not False
    gzip_min_size = _env_int("VODUM_HTTP_GZIP_MIN_BYTES", 1024, minimum=0)
    gzip_mimetypes = {
        "application/javascript",
        "application/json",
        "application/xml",
        "image/svg+xml",
        "text/css",
        "text/html",
        "text/javascript",
        "text/plain",
        "text/xml",
    }

    @app.after_request
    def gzip_text_response(response):
        if not gzip_enabled:
            return response
        if request.method == "HEAD" or "gzip" not in request.headers.get("Accept-Encoding", "").lower():
            return response
        if response.status_code < 200 or response.status_code in (204, 304):
            return response
        if response.direct_passthrough or response.is_streamed:
            return response
        if response.headers.get("Content-Encoding") or response.headers.get("Content-Range"):
            return response
        if request.path.startswith("/static"):
            return response
        if response.mimetype not in gzip_mimetypes:
            return response

        content_length = response.calculate_content_length()
        if content_length is not None and content_length < gzip_min_size:
            return response

        payload = response.get_data()
        if len(payload) < gzip_min_size:
            return response

        compressed = gzip.compress(payload)
        if len(compressed) >= len(payload):
            return response

        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
        response.headers.add("Vary", "Accept-Encoding")
        response.headers.pop("ETag", None)
        return response

    # i18n (requires DB access)
    init_i18n(app, get_db)

    # Context processor + template filters
    app.context_processor(inject_brand_name)
    app.template_filter("safe_datetime")(safe_datetime)
    app.template_filter("cron_human")(cron_human)
    app.template_filter("tz")(tz_filter)
    app.template_filter("browser_datetime")(browser_datetime)
    app.template_filter("utc_iso")(utc_iso)

    # DB teardown
    app.teardown_appcontext(close_db)

    # Blueprints
    app.register_blueprint(subscriptions_api)
    app.register_blueprint(users_bp)

    # Routes
    from routes import register_routes
    register_routes(app)

    # Expose helpers pour d’éventuels scripts internes
    app.get_db = get_db
    app.table_exists = table_exists
    app.scheduler_db_provider = lambda: DBManager(app.config["DATABASE"])

    _run_application_startup(app)

    return app





