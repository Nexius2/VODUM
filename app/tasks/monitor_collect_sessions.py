from __future__ import annotations

import json
from logging_utils import get_logger
from core.monitoring.collector import collect_sessions

logger = get_logger("monitor_collect_sessions")

def run(task_id: int, db):
    report = collect_sessions(db)

    # Log en base (onglet logs)
    db.execute(
        "INSERT INTO logs(level, category, message, details) VALUES (?, ?, ?, ?)",
        ("INFO", "monitoring", "monitor_collect_sessions completed", json.dumps(report, ensure_ascii=False)),
    )

    # Log txt (logging_utils)
    logger.info(f"[TASK {task_id}] report={report}")
