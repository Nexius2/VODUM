import threading


class TaskRuntimeSignals:
    """Thread-safe, in-memory signals consumed by the task scheduler."""

    def __init__(self, *, auto_enable_dirty=True):
        self._lock = threading.Lock()
        self._forced_task_runs = set()
        self._auto_enable_dirty = bool(auto_enable_dirty)

    def mark_auto_enable_dirty(self):
        with self._lock:
            self._auto_enable_dirty = True

    def consume_auto_enable_dirty(self) -> bool:
        with self._lock:
            if not self._auto_enable_dirty:
                return False
            self._auto_enable_dirty = False
            return True

    def force_task_run(self, task_name: str):
        normalized_name = str(task_name or "").strip()
        if not normalized_name:
            raise ValueError("task_name must not be empty")

        with self._lock:
            self._forced_task_runs.add(normalized_name)

    def consume_forced_task_run(self, task_name: str) -> bool:
        normalized_name = str(task_name or "").strip()
        if not normalized_name:
            return False

        with self._lock:
            if normalized_name not in self._forced_task_runs:
                return False
            self._forced_task_runs.remove(normalized_name)
            return True
