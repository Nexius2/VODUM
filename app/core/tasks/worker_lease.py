import threading


class WorkerLease:
    """Thread-safe ownership flag for a single in-process task worker."""

    def __init__(self):
        self._lock = threading.Lock()
        self._claimed = False

    def claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True

    def release(self):
        with self._lock:
            self._claimed = False

    def is_claimed(self) -> bool:
        with self._lock:
            return self._claimed
