import logging
import os
import re
import sqlite3
import time
from logging.handlers import RotatingFileHandler

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

LOG_DIR = "/logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

DB_PATH = os.environ.get("VODUM_DB", "/appdata/database.db")

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
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT debug_mode FROM settings WHERE id = 1")
        row = cur.fetchone()
        conn.close()

        value = bool(row and row[0] == 1)

    except Exception:
        value = False  # fail-safe

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
