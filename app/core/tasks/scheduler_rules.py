from datetime import datetime, timedelta


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


