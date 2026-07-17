class TaskConfigurationService:
    """Persist task enablement without coupling it to scheduler orchestration."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _enabled(value):
        return 1 if int(value) == 1 else 0

    def set_task_enabled(self, task_id, enabled):
        enabled = self._enabled(enabled)
        if enabled:
            self.db.execute(
                """UPDATE tasks SET enabled=1, status='idle', last_error=NULL,
                   next_run=NULL, retry_count=0, next_retry_at=NULL,
                   last_attempt_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (task_id,),
            )
        else:
            self.db.execute(
                "UPDATE tasks SET enabled=0, status='disabled', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )
        return True

    def set_tasks_enabled_by_names(self, task_names, enabled):
        if not task_names:
            return False
        enabled = self._enabled(enabled)
        placeholders = ",".join("?" for _ in task_names)
        self.db.execute(
            f"""UPDATE tasks SET enabled=?,
                status=CASE WHEN ?=1 THEN 'idle' ELSE 'disabled' END,
                updated_at=CURRENT_TIMESTAMP WHERE name IN ({placeholders})""",
            (enabled, enabled, *task_names),
        )
        return True

    def set_task_enabled_for_auto_mode(self, task_id, enabled):
        enabled = self._enabled(enabled)
        if enabled:
            self.db.execute(
                """UPDATE tasks SET enabled=1,
                   status=CASE WHEN status='disabled' OR status IS NULL OR TRIM(status)=''
                               THEN 'idle' ELSE status END,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (task_id,),
            )
        else:
            self.db.execute(
                """UPDATE tasks SET enabled=0,
                   status=CASE WHEN status IN ('running','queued') THEN status ELSE 'disabled' END,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (task_id,),
            )
        return True

    def set_tasks_enabled_by_names_for_auto_mode(self, task_names, enabled):
        if not task_names:
            return False
        enabled = self._enabled(enabled)
        placeholders = ",".join("?" for _ in task_names)
        if enabled:
            sql = f"""UPDATE tasks SET enabled=1,
                status=CASE WHEN status='disabled' OR status IS NULL OR TRIM(status)=''
                            THEN 'idle' ELSE status END,
                updated_at=CURRENT_TIMESTAMP WHERE name IN ({placeholders})"""
        else:
            sql = f"""UPDATE tasks SET enabled=0,
                status=CASE WHEN status IN ('running','queued') THEN status ELSE 'disabled' END,
                updated_at=CURRENT_TIMESTAMP WHERE name IN ({placeholders})"""
        self.db.execute(sql, tuple(task_names))
        return True

    def ensure_tasks_enabled(self, task_names):
        if not task_names:
            return False
        placeholders = ",".join("?" for _ in task_names)
        self.db.execute(
            f"""UPDATE tasks SET enabled=1,
                status=CASE WHEN status='disabled' OR status IS NULL OR TRIM(status)=''
                            THEN 'idle' ELSE status END,
                updated_at=CURRENT_TIMESTAMP WHERE name IN ({placeholders})""",
            tuple(task_names),
        )
        return True

    def apply_cron_master_switch(self, enabled):
        enabled = self._enabled(enabled)
        if not enabled:
            self.db.execute(
                """UPDATE tasks SET enabled_prev=CASE WHEN enabled_prev IS NULL THEN enabled ELSE enabled_prev END,
                   enabled=0, status='disabled', updated_at=CURRENT_TIMESTAMP"""
            )
        else:
            self.db.execute(
                """UPDATE tasks SET
                   enabled=CASE WHEN enabled_prev IS NULL THEN enabled ELSE enabled_prev END,
                   status=CASE WHEN (CASE WHEN enabled_prev IS NULL THEN enabled ELSE enabled_prev END)=1
                               THEN 'idle' ELSE 'disabled' END,
                   enabled_prev=NULL, updated_at=CURRENT_TIMESTAMP"""
            )
        return True

    def sync_expiry_tasks_from_settings(self, expiry_mode, cron_enabled):
        expiry_mode = (expiry_mode or "none").strip()
        cron_enabled = self._enabled(cron_enabled)
        desired = {
            "disable_expired_users": 1 if expiry_mode == "disable" else 0,
            "expired_subscription_manager": 1 if expiry_mode in ("warn_only", "warn_then_disable") else 0,
        }
        if cron_enabled:
            for name, enabled in desired.items():
                row = self.db.query_one("SELECT id FROM tasks WHERE name=?", (name,))
                if row:
                    self.set_task_enabled(int(row["id"]), enabled)
        else:
            for name, enabled in desired.items():
                self.db.execute("UPDATE tasks SET enabled_prev=? WHERE name=?", (enabled, name))
        return True

    @staticmethod
    def prepare_restored_database(restored_db):
        restored_db.execute("UPDATE settings SET maintenance_mode=1 WHERE id=1")
        restored_db.execute(
            """UPDATE tasks SET
               enabled_prev=CASE WHEN enabled_prev IS NULL THEN enabled ELSE enabled_prev END,
               enabled=0, status='disabled', updated_at=CURRENT_TIMESTAMP"""
        )
        return True
