import logging
import os
import re
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from db_manager import open_sqlite_connection

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

LOG_DIR = os.environ.get("VODUM_LOG_DIR")
if not LOG_DIR:
    LOG_DIR = (
        os.path.join(tempfile.gettempdir(), "vodum", "logs")
        if os.name == "nt"
        else "/appdata/logs"
    )
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

DB_PATH = os.environ.get("DATABASE_PATH") or "/appdata/database.db"

# Cache debug_mode
DEBUG_CACHE_TTL = 10  # secondes
_DEBUG_CACHE = {
    "value": False,
    "last_check": 0.0
}

# -------------------------------------------------------------------
# LOGGER ROOT
# -------------------------------------------------------------------

logger = logging.getLogger("vodum")
logger.setLevel(logging.DEBUG)  # On capture tout, filtrage via filter

handler = next(
    (item for item in logger.handlers if getattr(item, "_vodum_file_handler", False)),
    None,
)
if handler is None:
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
        delay=True,
    )
    handler._vodum_file_handler = True
    logger.addHandler(handler)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

handler.setFormatter(formatter)
logger.propagate = False  # Pas de duplication stdout


# -------------------------------------------------------------------
# HELPERS DB (avec cache)
# -------------------------------------------------------------------

def is_debug_mode_enabled() -> bool:
    """
    Retourne settings.debug_mode avec cache mémoire TTL.
    Sécurité maximale par défaut : False.
    Fonctionne sans UI, sans Flask, en tâche de fond.
    """
    now = time.time()

    # Cache valide
    if now - _DEBUG_CACHE["last_check"] < DEBUG_CACHE_TTL:
        return _DEBUG_CACHE["value"]

    # Rafraîchissement DB
    conn = None
    try:
        conn = open_sqlite_connection(DB_PATH, read_only=True)
        row = conn.execute("SELECT debug_mode FROM settings WHERE id = 1").fetchone()

        value = bool(row and row[0] == 1)

    except Exception:
        value = False  # fail-safe
    finally:
        if conn is not None:
            conn.close()

    _DEBUG_CACHE["value"] = value
    _DEBUG_CACHE["last_check"] = now

    return value


def update_debug_mode_cache(enabled: bool) -> None:
    """Apply a saved debug setting immediately in the current process."""
    _DEBUG_CACHE["value"] = bool(enabled)
    _DEBUG_CACHE["last_check"] = time.time()


# -------------------------------------------------------------------
# LOG FILTERS
# -------------------------------------------------------------------

class DebugModeFilter(logging.Filter):
    """Keep DEBUG records only while the application debug option is enabled."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.INFO or is_debug_mode_enabled()


class AnonymizeFilter(logging.Filter):
    """
    - Masque la partie locale des emails (avant @)
    - Masque tous les tokens / Authorization / Bearer
    - Désactivé automatiquement si debug_mode = 1
    """

    EMAIL_REGEX = re.compile(
        r'([a-zA-Z0-9._%+-])([a-zA-Z0-9._%+-]*)(@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    )

    TOKEN_REGEX = re.compile(
        r'(?i)\b(x-plex-token|token|authorization|bearer)\b\s*[:=]\s*[a-z0-9\-._]+'
    )

    BEARER_REGEX = re.compile(
        r'(?i)(authorization\s*:\s*bearer\s+)([a-z0-9\-._~+/]+=*)'
    )

    QUERY_TOKEN_REGEX = re.compile(
        r'(?i)(x-plex-token=|token=)([^&\s]+)'
    )

    IP_REGEX = re.compile(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    )

    def __init__(self, *, force=False):
        super().__init__()
        self.force = bool(force)

    def anonymize(self, value: str) -> str:
        msg = str(value or "")
        msg = self.EMAIL_REGEX.sub(
            lambda m: f"{m.group(1)}{'*' * len(m.group(2))}{m.group(3)}", msg
        )
        msg = self.BEARER_REGEX.sub(
            lambda m: f"{m.group(1)}***REDACTED***", msg
        )
        msg = self.TOKEN_REGEX.sub(
            lambda m: f"{m.group(1)}=***REDACTED***", msg
        )
        msg = self.QUERY_TOKEN_REGEX.sub(
            lambda m: f"{m.group(1)}***REDACTED***", msg
        )
        return self.IP_REGEX.sub("***.***.***.***", msg)

    def filter(self, record: logging.LogRecord) -> bool:
        # 🧪 Debug actif → logs NON anonymisés
        if not self.force and is_debug_mode_enabled():
            return True

        msg = self.anonymize(record.getMessage())

        # 📧 Email → masquer uniquement avant @
        msg = self.EMAIL_REGEX.sub(
            lambda m: f"{m.group(1)}{'*' * len(m.group(2))}{m.group(3)}",
            msg
        )

        # 🔑 Tokens → REDACTED
        msg = self.TOKEN_REGEX.sub(
            lambda m: f"{m.group(1)}=***REDACTED***",
            msg
        )

        # Bearer tokens
        msg = self.BEARER_REGEX.sub(
            lambda m: f"{m.group(1)}***REDACTED***",
            msg
        )

        # Querystring tokens
        msg = self.QUERY_TOKEN_REGEX.sub(
            lambda m: f"{m.group(1)}***REDACTED***",
            msg
        )

        # IP anonymization
        msg = self.IP_REGEX.sub(
            "***.***.***.***",
            msg
        )

        record.msg = msg
        record.args = ()

        # Tracebacks are formatted after filters. Sanitize the pre-rendered
        # exception text so exception messages cannot leak secrets to app.log.
        if record.exc_info:
            record.exc_text = self.anonymize(
                logging.Formatter().formatException(record.exc_info)
            )

        return True

def read_last_logs(limit=10):
    """
    Retourne les N dernières lignes du fichier de log.
    Centralisé ici pour éviter toute duplication.
    """
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return f.readlines()[-limit:]
    except FileNotFoundError:
        return []

def read_all_logs():
    return read_logs_snapshot()["lines"]


def read_logs_snapshot():
    lines = []
    errors = []
    paths = [f"{LOG_FILE}.{index}" for index in range(handler.backupCount, 0, -1)]
    paths.append(LOG_FILE)
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines.extend(f.readlines())
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append({"path": os.path.basename(path), "error": type(exc).__name__})
    return {"lines": lines, "errors": errors}


LOG_RECORD_RE = re.compile(
    r"^(?P<created_at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)"
    r"\s*\|\s*(?P<level>[A-Z]+)\s*\|\s*(?P<source>[^|]+?)\s*\|\s*(?P<message>.*)$"
)


def parse_log_records(lines):
    """Group traceback and continuation lines with their originating event."""
    records = []
    current = None
    for raw_line in lines:
        line = str(raw_line).rstrip("\r\n")
        match = LOG_RECORD_RE.match(line)
        if match:
            current = match.groupdict()
            records.append(current)
        elif current is not None:
            current["message"] += f"\n{line}"
        elif line:
            records.append({"created_at": "", "level": "INFO", "source": "system", "message": line})
    return records


# -------------------------------------------------------------------
# ATTACH FILTER
# -------------------------------------------------------------------

if not any(getattr(item, "_vodum_debug_mode_filter", False) for item in handler.filters):
    debug_mode_filter = DebugModeFilter()
    debug_mode_filter._vodum_debug_mode_filter = True
    handler.addFilter(debug_mode_filter)

if not any(getattr(item, "_vodum_anonymizer", False) for item in handler.filters):
    anonymizer = AnonymizeFilter()
    anonymizer._vodum_anonymizer = True
    handler.addFilter(anonymizer)


# -------------------------------------------------------------------
# PUBLIC API
# -------------------------------------------------------------------

def get_logger(name: str):
    """
    Retourne un logger enfant :
    ex: vodum.sync_plex, vodum.tasks_engine
    """
    return logger.getChild(name)
