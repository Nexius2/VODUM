"""Repair structurally impossible access relationships."""

from core.data_consistency import repair_access_consistency
from logging_utils import get_logger
from tasks_engine import task_logs


log = get_logger("cleanup_data_consistency")


def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_data_consistency started")
    stats = repair_access_consistency(db)
    message = (
        f"Access consistency cleanup: deleted={stats['deleted']}, "
        f"orphan_media_users={stats['orphan_media_users']}, "
        f"orphan_libraries={stats['orphan_libraries']}, "
        f"cross_server={stats['cross_server']}, remaining={stats['remaining']}."
    )
    log.info(message)
    task_logs(task_id, "success" if stats["remaining"] == 0 else "warning", message)
    return stats
