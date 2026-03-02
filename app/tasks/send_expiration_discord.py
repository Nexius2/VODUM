"""send_expiration_discord.py — deprecated

The unified Communications system is now handled by send_expiration_emails.py
(kept for backward compatibility of task names).

This task remains as a no-op to avoid double notifications if it is still
enabled in the database.
"""

from logging_utils import get_logger
from tasks.task_logs import task_logs

log = get_logger("send_expiration_discord")


def run(task_id: int | None = None):
    task_logs(task_id, "warning", "Task send_expiration_discord is deprecated (handled by unified communications)")
    log.warning("Task send_expiration_discord is deprecated (handled by unified communications)")
    return
