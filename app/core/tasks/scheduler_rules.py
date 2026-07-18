from datetime import datetime, timedelta


def parse_scheduler_datetime(value):
    """Return a scheduler datetime or None for missing/invalid persisted values."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def normalize_counter(value) -> int:
    """Normalize nullable or malformed database counters without raising."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def retry_is_pending(status, next_retry_at, retry_count, max_retries) -> bool:
    return (
        str(status or "").strip().lower() == "error"
        and next_retry_at is not None
        and normalize_counter(retry_count) < normalize_counter(max_retries)
    )


def task_is_busy(status, queued_count) -> bool:
    return (
        str(status or "").strip().lower() in {"running", "queued"}
        or normalize_counter(queued_count) > 0
    )


def scheduled_run_is_due(next_run, now, *, forced=False) -> bool:
    return bool(forced or (next_run is not None and next_run <= now))


def retry_modifier_for_attempt(next_attempt_number: int) -> str:
    """
    Standard scheduler backoff:
    1 -> +1 minute
    2 -> +5 minutes
    3 -> +15 minutes
    4+ -> +30 minutes
    """
    if next_attempt_number <= 1:
        return "+1 minute"
    if next_attempt_number == 2:
        return "+5 minutes"
    if next_attempt_number == 3:
        return "+15 minutes"
    return "+30 minutes"


def compute_next_task_run(schedule, schedule_mode, interval_seconds, base_time):
    """
    Compute the next scheduler run for interval and cron task modes.
    """
    schedule_mode = (schedule_mode or "cron").strip().lower()

    try:
        interval_seconds = int(interval_seconds or 0)
    except Exception:
        interval_seconds = 0

    if schedule_mode == "interval" and interval_seconds > 0:
        return base_time + timedelta(seconds=interval_seconds)

    from croniter import croniter

    return croniter(schedule, base_time).get_next(datetime)


