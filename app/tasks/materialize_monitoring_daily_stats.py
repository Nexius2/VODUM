"""Refresh compact daily Monitoring aggregates."""

from core.monitoring.daily_stats import refresh_recent_days
from tasks_engine import task_logs


def run(task_id: int, db):
    task_logs(task_id, "info", "Monitoring daily aggregate refresh started")
    result = refresh_recent_days(db, 31)
    task_logs(task_id, "success", f"Monitoring daily aggregates refreshed: {result['days']} days, {result['sessions']} sessions")
    return result
