"""Delete expired native accounts/shares before their local VODUM record."""
from core.expired_user_deletion import delete_expired_user
from tasks_engine import task_logs


def run(task_id, db):
    settings = db.query_one("SELECT expiry_mode,enable_cron_jobs FROM settings WHERE id=1")
    if not settings or settings["expiry_mode"] != "delete" or not settings["enable_cron_jobs"]:
        return
    users = db.query("SELECT id FROM vodum_users WHERE expiration_date IS NOT NULL ORDER BY id") or []
    deleted = failed = skipped = 0
    for user in users:
        result = delete_expired_user(db, int(user["id"]))
        for account in result["confirmed"]:
            task_logs(task_id, "info", f"Expiration deletion confirmed: user={user['id']} server={account['server_id']} media_user={account['media_user_id']}")
        if result["status"] == "deleted":
            deleted += 1
            task_logs(task_id, "info", f"Expiration deletion completed: user={user['id']} removed locally after native confirmation")
        elif result["status"] == "failed":
            failed += 1
            task_logs(task_id, "warning", f"Expiration deletion retained user={user['id']}: {result['reason']}")
        else:
            skipped += 1
            if result["reason"] != "not_eligible":
                task_logs(task_id, "info", f"Expiration deletion skipped user={user['id']}: {result['reason']}")
    task_logs(task_id, "info", f"Expiration deletion: deleted={deleted}, failed={failed}, skipped={skipped}")
    if failed:
        raise RuntimeError(f"Native deletion unconfirmed for {failed} user(s); local records retained for retry")
