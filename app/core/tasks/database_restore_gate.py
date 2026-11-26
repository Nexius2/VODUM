"""Pause background workers during an in-process database replacement."""

from contextlib import contextmanager
from threading import Condition


class DatabaseRestoreGate:
    def __init__(self):
        self._condition = Condition()
        self._active = 0
        self._restoring = False
        self._restart_pending = False

    def blocked(self):
        with self._condition:
            return self._restoring or self._restart_pending

    @contextmanager
    def background(self):
        with self._condition:
            allowed = not (self._restoring or self._restart_pending)
            if allowed:
                self._active += 1
        try:
            yield allowed
        finally:
            if allowed:
                with self._condition:
                    self._active -= 1
                    self._condition.notify_all()

    @contextmanager
    def restore(self):
        with self._condition:
            self._restoring = True
            self._condition.wait_for(lambda: self._active == 0)
        try:
            yield
        finally:
            with self._condition:
                self._restoring = False

    def pause_until_restart(self):
        with self._condition:
            self._restart_pending = True


database_restore_gate = DatabaseRestoreGate()
