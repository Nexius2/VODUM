import threading
from collections import deque


class TaskSequenceQueue:
    """FIFO sequence queue that guarantees ownership by at most one worker."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items = deque()
        self._worker_running = False

    def enqueue(self, task_names) -> bool:
        """Add a sequence and return True when the caller must start a worker."""
        sequence = tuple(task_names or ())
        if not sequence:
            raise ValueError("task sequence must not be empty")

        with self._lock:
            self._items.append(sequence)
            if self._worker_running:
                return False
            self._worker_running = True
            return True

    def take_next(self):
        """Take the next sequence, releasing worker ownership when empty."""
        with self._lock:
            if not self._items:
                self._worker_running = False
                return None
            return list(self._items.popleft())

    def pending_count(self) -> int:
        with self._lock:
            return len(self._items)

    def worker_is_running(self) -> bool:
        with self._lock:
            return self._worker_running
