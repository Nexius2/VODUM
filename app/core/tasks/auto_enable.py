from core.tasks.auto_enable_rules import MONITORING_TASKS, enabled_from_count


class TaskAutoEnableService:
    """Apply task enablement decisions from current database state."""

    def __init__(self, db, set_task, set_tasks, sync_expiry, force_run, logger):
        self.db = db
        self.set_task = set_task
        self.set_tasks = set_tasks
        self.sync_expiry = sync_expiry
        self.force_run = force_run
        self.logger = logger

    def _count(self, sql, params=()):
        row = self.db.query_one(sql, params) if params else self.db.query_one(sql)
        return row["cnt"] if row else 0

    def _set_named_task(self, task_name, enabled):
        row = self.db.query_one("SELECT id FROM tasks WHERE name = ?", (task_name,))
        if row:
            self.set_task(int(row["id"]), int(bool(enabled)))

    def monitoring(self):
        count = self._count(
            "SELECT COUNT(*) AS cnt FROM servers "
            "WHERE LOWER(TRIM(type)) IN ('plex', 'jellyfin')"
        )
        self.set_tasks(MONITORING_TASKS, enabled_from_count(count))

    def sync_providers(self):
        for provider, task_name in (("plex", "sync_plex"), ("jellyfin", "sync_jellyfin")):
            count = self._count(
                "SELECT COUNT(*) AS cnt FROM servers WHERE LOWER(TRIM(type)) = ?",
                (provider,),
            )
            self._set_named_task(task_name, enabled_from_count(count))

    def access_worker(self, provider):
        server_up = self._count(
            "SELECT COUNT(*) AS cnt FROM servers WHERE LOWER(TRIM(type)) = ? "
            "AND LOWER(TRIM(COALESCE(status, 'unknown'))) = 'up'",
            (provider,),
        )
        pending = self._count(
            "SELECT COUNT(*) AS cnt FROM media_jobs mj JOIN servers s ON s.id = mj.server_id "
            "WHERE mj.processed = 0 AND LOWER(TRIM(s.type)) = ?",
            (provider,),
        )
        self._set_named_task(
            f"apply_{provider}_access_updates",
            enabled_from_count(server_up) or enabled_from_count(pending),
        )

    def stream_enforcer(self):
        policies = self._count(
            "SELECT COUNT(*) AS cnt FROM stream_policies WHERE is_enabled = 1"
        )
        if enabled_from_count(policies):
            self._set_named_task("stream_enforcer", 1)

    def expiry(self):
        settings = self.db.query_one(
            "SELECT expiry_mode, enable_cron_jobs FROM settings WHERE id = 1"
        )
        if not settings:
            return
        mode = str(settings["expiry_mode"] or "none").strip()
        cron_enabled = int(settings["enable_cron_jobs"] or 1)
        self.sync_expiry(mode, cron_enabled)
        if mode in ("warn_only", "warn_then_disable"):
            self.force_run("expired_subscription_manager")

    def run_pass(self):
        steps = (
            ("sync tasks", self.sync_providers),
            ("monitoring tasks", self.monitoring),
            ("stream_enforcer", self.stream_enforcer),
            ("apply_plex_access_updates", lambda: self.access_worker("plex")),
            ("apply_jellyfin_access_updates", lambda: self.access_worker("jellyfin")),
            ("expiry tasks", self.expiry),
        )
        for label, step in steps:
            try:
                step()
            except Exception:
                self.logger.warning("Auto-enable failed: %s", label, exc_info=True)
