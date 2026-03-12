from logging_utils import get_logger
from external.dashboard_quote_easter_egg import refresh_dashboard_quote_cache

logger = get_logger("refresh_dashboard_quote_cache")


def run(task_id: int, db):
    logger.info(f"[TASK {task_id}] Starting dashboard quote cache refresh")

    payload = refresh_dashboard_quote_cache(force=False)

    logger.info(f"[TASK {task_id}] Result: {payload}")

    return payload