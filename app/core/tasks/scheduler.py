from core.tasks.scheduler_rules import (
    normalize_counter,
    parse_scheduler_datetime,
    retry_is_pending,
    scheduled_run_is_due,
    task_is_busy,
)


TASKS_FOR_SCHEDULER_SQL = """
SELECT id, name, schedule, schedule_mode, interval_seconds, enabled,
       last_run, next_run, status, queued_count, retry_count,
       max_retries, next_retry_at
FROM tasks WHERE enabled = 1
"""


class TaskScheduler:
    """Database-backed scheduler tick, independent from its sleeping loop."""

    def __init__(self, db, enqueue, compute_next, consume_forced, auto_enable, logger):
        self.db = db
        self.enqueue = enqueue
        self.compute_next = compute_next
        self.consume_forced = consume_forced
        self.auto_enable = auto_enable
        self.logger = logger

    def tick(self, now, run_auto_enable=True):
        if run_auto_enable:
            self.auto_enable()
        try:
            rows = self.db.query(TASKS_FOR_SCHEDULER_SQL)
        except Exception:
            self.logger.error("Scheduler unable to load enabled tasks", exc_info=True)
            return False

        for row in rows:
            self._process_row(row, now)
        return True

    def _process_row(self, row, now):
        task_id = row["id"]
        name = row["name"]
        status = row["status"]
        next_retry_at = parse_scheduler_datetime(row["next_retry_at"])
        if retry_is_pending(
            status, next_retry_at, row["retry_count"], row["max_retries"]
        ):
            if next_retry_at <= now:
                if self.enqueue(task_id):
                    self.db.execute(
                        "UPDATE tasks SET next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (task_id,),
                    )
                else:
                    self.logger.warning("Retry enqueue refused | task=%s | id=%s", name, task_id)
            return

        schedule = row["schedule"]
        if not schedule or task_is_busy(status, row["queued_count"]):
            return

        schedule_mode = row["schedule_mode"]
        interval_seconds = row["interval_seconds"]
        last_run = row["last_run"]
        next_exec = parse_scheduler_datetime(row["next_run"])
        if next_exec is None:
            base = parse_scheduler_datetime(last_run) or now
            next_exec = self.compute_next(schedule, schedule_mode, interval_seconds, base)
            self.db.execute("UPDATE tasks SET next_run = ? WHERE id = ?", (next_exec, task_id))

        if last_run is None:
            if next_exec > now or not self.enqueue(task_id):
                return
            self._advance(task_id, schedule, schedule_mode, interval_seconds, now)
            self.db.execute(
                "UPDATE tasks SET last_run = datetime('now'), updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND last_run IS NULL",
                (task_id,),
            )
            return

        forced = self.consume_forced(name)
        if scheduled_run_is_due(next_exec, now, forced=forced):
            if not self.enqueue(task_id):
                self.logger.warning("Scheduled enqueue refused | task=%s | id=%s", name, task_id)
                return
            self._advance(task_id, schedule, schedule_mode, interval_seconds, now)

    def _advance(self, task_id, schedule, schedule_mode, interval_seconds, now):
        next_future = self.compute_next(schedule, schedule_mode, interval_seconds, now)
        self.db.execute(
            "UPDATE tasks SET next_run = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (next_future, task_id),
        )
