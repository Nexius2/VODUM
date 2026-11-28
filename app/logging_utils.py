import logging
import os
import re
import tempfile
import time
import threading
import sys
from collections import defaultdict
from core.log_retention import RetentionFileHandler
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

def read_log_retention_policy():
    conn = None
    try:
        conn = open_sqlite_connection(DB_PATH, read_only=True)
        row = conn.execute("SELECT log_retention_days, log_max_size_mb FROM settings WHERE id=1").fetchone()
        if row:
            from core.log_retention import validate_log_retention
            return validate_log_retention(row[0], row[1])
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()
    return 30, 50


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
    handler = RetentionFileHandler(LOG_FILE, read_log_retention_policy)
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
        r'(?i)\b(x-plex-token|token|authorization|bearer|password|secret|api[_-]?key)\b\s*[:=]\s*[^\s,;&]+'
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
        exc_info = getattr(record, "exc_info", None)
        if exc_info:
            record.exc_text = self.anonymize(
                logging.Formatter().formatException(exc_info)
            )

        return True

def read_last_logs(limit=10):
    """
    Retourne les N dernières lignes du fichier de log.
    Centralisé ici pour éviter toute duplication.
    """
    limit = int(limit)
    if limit <= 0:
        return []
    try:
        # Read backwards in blocks; dashboard cost must not grow with log size.
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            position = f.tell()
            chunks = []
            newline_count = 0
            while position > 0 and newline_count <= limit:
                size = min(8192, position)
                position -= size
                f.seek(position)
                chunk = f.read(size)
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")
        tail = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
        return tail.replace("\r\n", "\n").splitlines(keepends=True)[-limit:]
    except FileNotFoundError:
        return []


def read_all_logs():
    return read_logs_snapshot()["lines"]


def read_logs_snapshot():
    lines = []
    errors = []
    try:
        handler.maintain(force=True)
    except OSError as exc:
        errors.append({"path": "app.log", "error": type(exc).__name__})
    paths = handler.paths()
    return _read_log_paths(paths, errors)


def _read_log_paths(paths, errors):
    lines = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines.extend(f.readlines())
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append({"path": os.path.basename(path), "error": type(exc).__name__})
    return {"lines": lines, "errors": errors}


_LOG_RECORDS_LOCK = threading.Lock()
_LOG_RECORDS_CACHE = None
_LOG_ARCHIVE_CACHE = None
_LOG_RECORDS_CACHE_MAX_BYTES = 8 * 1024 * 1024
_LOG_SEARCH_CACHE = None
_LOG_SEARCH_CACHE_MAX_BYTES = 512 * 1024


def _log_files_signature(paths):
    signature = []
    for path in paths:
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        signature.append((str(path), stat.st_ino, stat.st_size,
                          stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(signature)


def _log_records_fit_cache(records, by_level, limit=None):
    if limit is None:
        limit = _LOG_RECORDS_CACHE_MAX_BYTES
    size = sys.getsizeof(records) + sys.getsizeof(by_level)
    size += sum(sys.getsizeof(rows) for rows in by_level.values())
    for row in records:
        size += sys.getsizeof(row)
        size += sum(sys.getsizeof(key) + sys.getsizeof(value)
                    for key, value in row.items())
        if size > limit:
            return False
    return size <= limit


def _read_log_archives(paths, signature, errors):
    """Reuse parsed archives while the active log changes independently."""
    global _LOG_ARCHIVE_CACHE
    if not paths:
        _LOG_ARCHIVE_CACHE = None
        return []
    if signature is not None and _LOG_ARCHIVE_CACHE is not None:
        if _LOG_ARCHIVE_CACHE[0] == signature:
            return _LOG_ARCHIVE_CACHE[1]
    _LOG_ARCHIVE_CACHE = None
    archives = parse_log_records(_read_log_paths(paths, errors)["lines"])
    if not errors and signature is not None:
        try:
            stable = signature == _log_files_signature(paths)
        except OSError:
            stable = False
        if stable and _log_records_fit_cache(archives, {}, _LOG_RECORDS_CACHE_MAX_BYTES // 2):
            _LOG_ARCHIVE_CACHE = (signature, archives)
    return archives


def _read_log_records_index():
    """Reuse stable records and archived prefixes; exports still read raw lines.

    Keep one bounded cache, invalidate on append/rotation/retention, and never
    cache partial reads or files that changed while being read.
    """
    global _LOG_RECORDS_CACHE, _LOG_SEARCH_CACHE
    with _LOG_RECORDS_LOCK:
        errors = []
        try:
            handler.maintain(force=True)
        except OSError as exc:
            errors.append({"path": "app.log", "error": type(exc).__name__})
        paths = handler.paths()
        try:
            signature = _log_files_signature(paths)
        except OSError:
            signature = None
        if not errors and signature is not None and _LOG_RECORDS_CACHE is not None:
            if _LOG_RECORDS_CACHE[0] == signature:
                return _LOG_RECORDS_CACHE[1], _LOG_RECORDS_CACHE[2], []
        _LOG_RECORDS_CACHE = None
        _LOG_SEARCH_CACHE = None
        archive_paths, active_paths = paths[:-1], paths[-1:]
        archive_names = {str(path) for path in archive_paths}
        archive_signature = (
            tuple(item for item in signature if item[0] in archive_names)
            if signature is not None and not errors else None
        )
        archives = _read_log_archives(archive_paths, archive_signature, errors)
        snapshot = _read_log_paths(active_paths, errors)
        errors = snapshot["errors"]
        if archives and archives[-1]["created_at"]:
            records = archives[:-1] + parse_log_records(snapshot["lines"], previous=archives[-1])
        else:
            records = archives + parse_log_records(snapshot["lines"])
        by_level = defaultdict(list)
        for row in records:
            by_level[row["level"]].append(row)
        try:
            stable = signature is not None and signature == _log_files_signature(handler.paths())
        except OSError:
            stable = False
        if (stable and not snapshot["errors"]
                and sum(item[2] for item in signature) <= _LOG_RECORDS_CACHE_MAX_BYTES
                and _log_records_fit_cache(records, by_level)):
            _LOG_RECORDS_CACHE = (signature, records, by_level)
        return records, by_level, snapshot["errors"]


def read_log_records_snapshot():
    records, _, errors = _read_log_records_index()
    return {"records": [dict(row) for row in records], "errors": errors}


def _filter_log_records(selected, needle):
    return tuple(row for row in selected
                 if needle in " ".join(str(value) for value in row.values()).lower())


def _cached_log_search(records, selected, level, search):
    """Reuse one filter across pages while its complete source stays cached."""
    global _LOG_SEARCH_CACHE
    needle = search.lower()
    with _LOG_RECORDS_LOCK:
        cached = _LOG_SEARCH_CACHE
        if cached is not None and cached[0] is records and cached[1:3] == (level, needle):
            return cached[3]
    # Do not hold the shared file/cache lock during a potentially long scan.
    matches = _filter_log_records(selected, needle)
    with _LOG_RECORDS_LOCK:
        cache_bytes = (sys.getsizeof(matches) + sys.getsizeof(needle)
                       + sys.getsizeof(level) + sys.getsizeof((records, level, needle, matches)))
        if (_LOG_RECORDS_CACHE is not None and _LOG_RECORDS_CACHE[1] is records
                and cache_bytes <= _LOG_SEARCH_CACHE_MAX_BYTES):
            _LOG_SEARCH_CACHE = (records, level, needle, matches)
    return matches


def read_log_page(level, search, page, per_page):
    records, by_level, errors = _read_log_records_index()
    selected = records if level == "ALL" else by_level.get(level, ())
    if search:
        selected = _cached_log_search(records, selected, level, search)
    total_pages = max(1, (len(selected) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    end = len(selected) - (page - 1) * per_page
    start = max(0, end - per_page)
    return {
        "records": [dict(row) for row in reversed(selected[start:end])],
        "counts": {name: len(rows) for name, rows in by_level.items()},
        "errors": errors,
        "page": page,
        "total_pages": total_pages,
    }


LOG_RECORD_RE = re.compile(
    r"^(?P<created_at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)"
    r"\s*\|\s*(?P<level>[A-Z]+)\s*\|\s*(?P<source>[^|]+?)\s*\|\s*(?P<message>.*)$"
)


def parse_log_records(lines, *, previous=None):
    """Group traceback and continuation lines with their originating event."""
    current = dict(previous) if previous is not None else None
    records = [current] if current is not None else []
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
