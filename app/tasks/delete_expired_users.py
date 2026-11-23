"""Delete expired native accounts/shares before their local VODUM record."""
from core.expired_user_deletion import delete_expired_user
from tasks_engine import task_logs


def run(task_id, db):
    settings = db.query_one("SELECT expiry_mode,enable_cron_jobs FROM settings WHERE id=1")
    if not settings or settings["expiry_mode"] != "delete" or not settings["enable_cron_jobs"]:
        return
    users = db.query("SELECT id FROM vodum_users WHERE expiration_date IS NOT NULL ORDER BY id") or []
    deleted = failed = skipped = deferred = 0
    failures = []
    unavailable_servers = set()
    for user in users:
        result = delete_expired_user(db, int(user["id"]), unavailable_servers=unavailable_servers)
        for account in result["confirmed"]:
            task_logs(task_id, "info", f"Expiration deletion confirmed: user={user['id']} server={account['server_id']} media_user={account['media_user_id']}")
        if result["status"] == "deleted":
            deleted += 1
            task_logs(task_id, "info", f"Expiration deletion completed: user={user['id']} removed locally after native confirmation")
        elif result["status"] == "deferred":
            deferred += 1
            task_logs(task_id, "info",
                      f"Expiration deletion deferred: server={result.get('failed_server_id', 'unknown')} "
                      f"provider={result.get('failed_provider', 'unknown')} is unreachable or temporarily unavailable; "
                      f"user={user['id']} local records retained. No native deletion could be confirmed at "
                      f"step={result.get('failed_step', 'unknown')}; will check again on the next scheduled run.")
        elif result["status"] == "failed":
            failed += 1
            detail = (f"user={user['id']} server={result.get('failed_server_id', 'unknown')} "
                      f"media_user={result.get('failed_media_user_id', 'unknown')} "
                      f"provider={result.get('failed_provider', 'unknown')} "
                      f"step={result.get('failed_step', 'unknown')}: {result['reason']}")
            failures.append(detail)
            task_logs(task_id, "warning", "Expiration deletion retained " + detail)
        else:
            skipped += 1
            if result["reason"] != "not_eligible":
                task_logs(task_id, "info", f"Expiration deletion skipped user={user['id']}: {result['reason']}")
    task_logs(task_id, "info", f"Expiration deletion: deleted={deleted}, failed={failed}, deferred={deferred}, skipped={skipped}")
    if failed:
        raise RuntimeError(f"Native deletion unconfirmed for {failed} user(s); local records retained for retry. "
                           + "; ".join(failures[:10])
                           + (f"; {failed - 10} more failure(s) in task logs" if failed > 10 else ""))
