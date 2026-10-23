"""Cache the update badge until the status file changes."""
import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from utils.version import app_version_tuple

_lock = threading.Lock()
_signature = None
_value = (False, 0)
_data = {}


def _badge_value(data, local_version):
    available = data.get('update_available') is True
    if local_version is not None:
        local = app_version_tuple(local_version)
        remote = app_version_tuple(data.get('latest_version'))
        available = available and local is not None and remote is not None and remote > local
    if not available:
        return False, 0
    try:
        since = datetime.fromisoformat(data.get('update_available_since') or '')
        if since.tzinfo is not None:
            return True, max(0, (datetime.now(timezone.utc) - since).days)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return True, max(0, int(data.get('update_pending_days') or 0))
    except (TypeError, ValueError, OverflowError):
        return True, 0


def read_update_badge(path, local_version=None):
    global _signature, _value, _data
    path = Path(path)
    with _lock:
        try:
            stat = path.stat()
            signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_ctime_ns,
                         stat.st_size, stat.st_ino)
            if signature == _signature:
                return _badge_value(_data, local_version)
            with path.open('r', encoding='utf-8', errors='ignore') as source:
                data = json.load(source) or {}
            if not isinstance(data, dict):
                raise ValueError('Invalid update status')
            value = _badge_value(data, local_version)
            _data = data
            _signature, _value = signature, value
            return value
        except (OSError, ValueError, TypeError, AttributeError):
            # Retry errors next time; never retain a stale badge after deletion.
            _signature, _value = None, (False, 0)
            _data = {}
            return _value
