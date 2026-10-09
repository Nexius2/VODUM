"""Cache the update badge until the status file changes."""
import json
import threading
from pathlib import Path

_lock = threading.Lock()
_signature = None
_value = (False, 0)


def read_update_badge(path):
    global _signature, _value
    path = Path(path)
    with _lock:
        try:
            stat = path.stat()
            signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_ctime_ns,
                         stat.st_size, stat.st_ino)
            if signature == _signature:
                return _value
            with path.open('r', encoding='utf-8', errors='ignore') as source:
                data = json.load(source) or {}
            value = (bool(data.get('update_available')), int(data.get('update_pending_days') or 0))
            _signature, _value = signature, value
            return value
        except (OSError, ValueError, TypeError, AttributeError):
            # Retry errors next time; never retain a stale badge after deletion.
            _signature, _value = None, (False, 0)
            return _value
