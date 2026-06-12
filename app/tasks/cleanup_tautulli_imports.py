"""Clean old Tautulli import diagnostics and completed job records."""

from __future__ import annotations

import os
from pathlib import Path

from core.tautulli_cleanup import cleanup_tautulli_imports
from logging_utils import get_logger
from tasks_engine import task_logs


log = get_logger("cleanup_tautulli_imports")
IMPORTS_DIR = Path(os.environ.get("VODUM_IMPORTS_DIR", "/appdata/imports"))
RETENTION_DAYS = int(os.environ.get("VODUM_TAUTULLI_IMPORT_RETENTION_DAYS", "30"))
def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_tautulli_imports started")
    stats = cleanup_tautulli_imports(
        db,
        IMPORTS_DIR,
        RETENTION_DAYS,
        on_error=lambda path, exc: log.warning(
            f"Unable to clean Tautulli import artifact: {path}: {exc}", exc_info=True
        ),
    )
    message = (
        f"Tautulli import cleanup: deleted_files={stats['deleted_files']}, "
        f"deleted_jobs={stats['deleted_jobs']}, scanned={stats['scanned']}."
    )
    log.info(message)
    task_logs(task_id, "success", message)
    return stats
