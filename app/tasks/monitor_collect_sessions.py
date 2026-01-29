from __future__ import annotations

import json
from logging_utils import get_logger
from core.monitoring.collector import collect_sessions

logger = get_logger("monitor_collect_sessions")

def run(task_id: int, db):
    report = collect_sessions(db)

    # Log txt (logging_utils)
    logger.info(f"[TASK {task_id}] report={report}")
