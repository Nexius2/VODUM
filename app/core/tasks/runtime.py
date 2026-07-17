import threading
import time
from datetime import datetime


class SchedulerRuntime:
    """Own the scheduler lifecycle while keeping tasks_engine APIs stable."""

    def __init__(self, db, scheduler, cron_enabled, kick_worker, consume_dirty,
                 auto_enable, watchdog_loop, compute_next_run, logger, debug_enabled):
        self.db = db
        self.scheduler = scheduler
        self.cron_enabled = cron_enabled
        self.kick_worker = kick_worker
        self.consume_dirty = consume_dirty
        self.auto_enable = auto_enable
        self.watchdog_loop = watchdog_loop
        self.compute_next_run = compute_next_run
        self.logger = logger
        self.debug_enabled = debug_enabled
        self._start_lock = threading.Lock()
        self._started = False

    def recover_state(self):
        try:
            self.db.execute(
                """UPDATE tasks SET
                   status=CASE WHEN enabled=0 THEN status
                               WHEN queued_count>0 THEN 'queued' ELSE 'idle' END,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE status IN ('running','queued','idle')"""
            )
            if self.debug_enabled():
                self.logger.debug("Recovery tasks: reset running/queued states OK")
            self.kick_worker()
        except Exception as exc:
            self.logger.warning("Recovery tasks failed: %s", exc, exc_info=True)

    def loop(self):
        self.logger.info("VODUM scheduler started")
        self.recover_state()
        while True:
            if not self.cron_enabled():
                time.sleep(30)
                continue
            self.kick_worker()
            try:
                self.scheduler.tick(
                    datetime.now(), run_auto_enable=self.consume_dirty()
                )
            except Exception as exc:
                self.logger.error("Error scheduler (global): %s", exc, exc_info=True)
            time.sleep(30)

    def force_check_update(self):
        try:
            row = self.db.query_one(
                "SELECT id, enabled, status, queued_count FROM tasks WHERE name='check_update'"
            )
            if not row:
                self.logger.warning("check_update startup refresh skipped: task not found")
                return False
            task_id = int(row["id"])
            status = str(row["status"] or "").lower()
            if not int(row["enabled"] or 0):
                self.logger.warning("check_update startup refresh skipped: task disabled")
                return False
            if status in ("running", "queued") or int(row["queued_count"] or 0) > 0:
                if self.debug_enabled():
                    self.logger.debug("check_update startup refresh skipped: already queued/running")
                return False
            if not self.scheduler.enqueue(task_id):
                self.logger.warning("check_update startup refresh enqueue refused")
                return False
            try:
                next_run = self.compute_next_run("0 4 * * *", "cron", None, datetime.now())
                self.db.execute(
                    "UPDATE tasks SET next_run=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (next_run, task_id),
                )
            except Exception as exc:
                self.logger.warning(
                    "check_update startup refresh queued but next_run update failed: %s",
                    exc, exc_info=True,
                )
            self.logger.info("check_update startup refresh queued")
            return True
        except Exception as exc:
            self.logger.warning("check_update startup refresh failed: %s", exc, exc_info=True)
            return False

    def start(self):
        with self._start_lock:
            if self._started:
                if self.debug_enabled():
                    self.logger.debug("start_scheduler() ignored: scheduler already started")
                return False
            self._started = True
        self.logger.info("starting VODUM scheduler")
        threading.Thread(
            target=self.watchdog_loop, name="vodum-watchdog", daemon=True
        ).start()
        self.logger.info("Watchdog started")
        try:
            if self.cron_enabled():
                self.auto_enable()
                self.logger.info("Task auto-enable pass run at startup")
                self.force_check_update()
            else:
                self.logger.info("Cron disabled (global); skipping auto-enable at startup")
        except Exception as exc:
            self.logger.error("task auto-enable pass at startup failed: %s", exc, exc_info=True)
        threading.Thread(target=self.loop, name="vodum-scheduler", daemon=True).start()
        self.logger.info("Scheduler started")
        return True
