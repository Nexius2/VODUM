import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from db_manager import open_sqlite_connection

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

LOG_DIR = os.environ.get("VODUM_LOG_DIR", "/appdata/logs")
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

handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5_000_000,   # 5 Mo
    backupCount=5,
    encoding="utf-8"
)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

handler.setFormatter(formatter)
logger.addHandler(handler)
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


# -------------------------------------------------------------------
# LOG FILTER (ANONYMISATION)
# -------------------------------------------------------------------

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

    def filter(self, record: logging.LogRecord) -> bool:
        # 🧪 Debug actif → logs NON anonymisés
        if is_debug_mode_enabled():
            return True

        msg = record.getMessage()

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
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return f.readlines()
    except FileNotFoundError:
        return []


# -------------------------------------------------------------------
# ATTACH FILTER
# -------------------------------------------------------------------

handler.addFilter(AnonymizeFilter())


# -------------------------------------------------------------------
# PUBLIC API
# -------------------------------------------------------------------

def get_logger(name: str):
    """
    Retourne un logger enfant :
    ex: vodum.sync_plex, vodum.tasks_engine
    """
    return logger.getChild(name)


