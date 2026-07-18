import threading
import time

from core.tasks.sequence_queue import TaskSequenceQueue


class TaskSequenceRunner:
    """FIFO orchestration for blocking task sequences."""

    def __init__(self, db, enqueue_task, logger, debug_enabled, *, sleep=time.sleep, clock=time.time):
        self.db = db
        self.enqueue_task = enqueue_task
        self.logger = logger
        self.debug_enabled = debug_enabled
        self.sleep = sleep
        self.clock = clock
        self.queue = TaskSequenceQueue()

    def wait_for_completion(self, task_name, last_run_before=None, poll_interval=2, timeout=1800):
        started_at = self.clock()
        while True:
            row = self.db.query_one("SELECT status, last_run FROM tasks WHERE name=?", (task_name,))
            if not row:
                return
            status = str(row["status"] or "").lower().strip()
            last_run = row["last_run"]
            if status == "error":
                return
            if last_run_before is not None:
                if last_run is not None and str(last_run) != str(last_run_before):
                    return
            elif status in ("idle", "disabled"):
                return
            if self.clock() - started_at > timeout:
                raise TimeoutError(f"Timeout waiting for task '{task_name}' to complete")
            self.sleep(poll_interval)

    def enqueue(self, task_names):
        if self.queue.enqueue(task_names):
            threading.Thread(target=self._worker, name="vodum-sequence-worker", daemon=True).start()

    def _worker(self):
        while True:
            task_names = self.queue.take_next()
            if task_names is None:
                return
            try:
                self.run(task_names)
            except Exception:
                self.logger.exception("[QUEUE] Error while running sequence %s", task_names)

    def run(self, task_names):
        for task_name in task_names:
            row = self.db.query_one("SELECT id FROM tasks WHERE name=?", (task_name,))
            if not row:
                self.logger.error("[SEQ] Task unknown: %s", task_name)
                continue
            task_id = row["id"]
            before = self.db.query_one("SELECT last_run FROM tasks WHERE id=?", (task_id,))
            last_run_before = before["last_run"] if before else None
            if not self.enqueue_task(task_id):
                self.logger.warning("[SEQ] Task not enqueued, skipping wait: %s", task_name)
                continue
            self.wait_for_completion(task_name, last_run_before=last_run_before, timeout=1800)
        return True


def discovery_sequence_for_provider(server_type: str) -> list[str]:
    provider = str(server_type or "").strip().lower()
    if provider == "plex":
        return ["check_servers", "sync_plex"]
    if provider == "jellyfin":
        return ["check_servers", "sync_jellyfin"]
    return ["check_servers"]
