def seed_default_tasks(conn, cursor, *, ensure_row) -> None:
    # 3. Injecter les données par défaut
    # -------------------------------------------------

    # Tâche sync_plex
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "sync_plex",
        "description": "task_description.sync_plex",
        "schedule": "7 */6 * * *",  # toutes les 6h, décale les tâches lourdes
        "enabled": 0,
        "status": "disabled"
    })



    # Tâche cleanup_logs (suppression logs > 7 jours)
    #ensure_row(cursor, "tasks", "name = :name", {
    #    "name": "cleanup_logs",
    #    "description": "Suppression automatique des logs de plus de 7 jours",
    #    "schedule": "0 2 * * *",  # tous les jours à 02h00
    #    "enabled": 1,
    #    "status": "idle"
    #})

    # Tâche check_update (tous les jours)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_update",
        "description": "task_description.check_update",
        "schedule": "0 4 * * *",  # tous les jours à 04:00
        "enabled": 1,
        "status": "idle"
    })


    # Tâche backup automatique (tous les 3 jours à 03:00)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "auto_backup",
        "description": "task_description.auto_backup",
        "schedule": "0 3 */3 * *",   # tous les 3 jours
        "enabled": 1,
        "status": "idle"
    })

    # Restore backup (ON-DEMAND)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "restore_backup",
        "description": "task_description.restore_backup",
        "schedule": None,
        "enabled": 1,
        "status": "idle"
    })

    # Tâche cleanup des backups (supprime backups > 30 jours)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_backups",
        "description": "task_description.cleanup_backups",
        "schedule": "30 3 * * *",  # tous les jours à 03:30
        "enabled": 1,
        "status": "idle"
    })

    # Tâche cleanup des données (purge des historiques selon data_retention_years)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_data_retention",
        "description": "task_description.cleanup_data_retention",
        "schedule": "0 4 * * 0",  # chaque dimanche à 04:00
        "enabled": 1,
        "status": "idle"
    })

    # Tâche vérification intégrité DB
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "db_integrity_check",
        "description": "task_description.db_integrity_check",
        "schedule": "15 4 * * 0",  # chaque dimanche à 04:15
        "enabled": 1,
        "status": "idle"
    })

    # Tâche cleanup du cache artwork (posters/backdrops monitoring)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_artwork_cache",
        "description": "task_description.cleanup_artwork_cache",
        "schedule": "30 4 * * 0",  # chaque dimanche à 04:30
        "enabled": 1,
        "status": "idle"
    })

    # Tâche warmup du cache artwork (posters/backdrops monitoring)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "warmup_artwork_cache",
        "description": "task_description.warmup_artwork_cache",
        "schedule": "*/30 * * * *",  # toutes les 30 minutes
        "enabled": 1,
        "status": "idle"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_tautulli_imports",
        "description": "task_description.cleanup_tautulli_imports",
        "schedule": "45 4 * * 0",
        "enabled": 1,
        "status": "idle"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_data_consistency",
        "description": "task_description.cleanup_data_consistency",
        "schedule": "50 4 * * 0",
        "enabled": 1,
        "status": "idle"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "materialize_monitoring_daily_stats",
        "description": "task_description.materialize_monitoring_daily_stats",
        "schedule": "20 1 * * *",
        "enabled": 1,
        "status": "idle"
    })

    # Tâche update_user_status
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "update_user_status",
        "description": "task_description.update_user_status",
        "schedule": "5 * * * *",  # Toutes les heures, hors minute de pointe
        "enabled": 1,
        "status": "idle"
    })

    # Tâche check_servers (ping léger des serveurs toutes les 10 minutes)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_servers",
        "description": "task_description.check_servers",
        "schedule": "7,37 * * * *",  # toutes les 30 minutes, étalé
        "enabled": 1,
        "status": "idle"
    })

    # Tâche daily_unfriend_cleanup
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "cleanup_unfriended",
        "description": "task_description.cleanup_unfriended",
        "schedule": "0 4 * * *",  # tous les jours à 04h00
        "enabled": 1,
        "status": "idle"
    })

    # Scheduler monitoring (enqueue)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "monitor_enqueue_refresh",
        "description": "task_description.monitor_enqueue_refresh",
        "schedule": "*/3 * * * *",
        "enabled": 1,
        "status": "idle"
    })

    # Worker queue
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "media_jobs_worker",
        "description": "task_description.media_jobs_worker",
        "schedule": "*/1 * * * *",
        "enabled": 1,
        "status": "idle"
    })

    cursor.execute("""
        UPDATE tasks
        SET enabled = 1,
            status = CASE
                WHEN status = 'disabled' THEN 'idle'
                ELSE status
            END

        WHERE name IN ('monitor_enqueue_refresh', 'media_jobs_worker')
    """)

    # Tautulli import (ON-DEMAND)
    # - No cron schedule: it is launched manually when a Tautulli DB is uploaded.
    # - Keeping enabled=1 allows run_task_by_name('import_tautulli') to enqueue it.
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "import_tautulli",
        "description": "task_description.import_tautulli",
        "schedule": None,
        "enabled": 1,
        "status": "idle"
    })
    # --- FORCE import_tautulli en ON-DEMAND (pas de cron) ---
    cursor.execute("""
        UPDATE tasks
        SET
            schedule = NULL,
            next_run  = NULL,
            enabled   = 1,
            status    = CASE
                          WHEN status = 'running' THEN status
                          ELSE 'idle'
                        END,
            updated_at = CURRENT_TIMESTAMP
        WHERE name = 'import_tautulli'
    """)
    conn.commit()

    # Ajouter la tâche send_expiration_emails si absente
    cursor.execute("""
        SELECT 1 FROM tasks WHERE name = 'send_expiration_emails'
    """)
    exists = cursor.fetchone()

    if not exists:
        cursor.execute("""
            INSERT INTO tasks (name, schedule, enabled, status)
            VALUES ('send_expiration_emails', '27 * * * *', 0, 'disabled')
        """)
        print("➕ Task send_expiration_emails added.")

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_pending_invite_reminders",
        "description": "task_description.send_pending_invite_reminders",
        "schedule": "30 0 * * *",
        "enabled": 1,
        "status": "idle"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_telemetry",
        "description": "Send anonymous Vodum telemetry statistics.",
        "schedule": "23 * * * *",
        "enabled": 1,
        "status": "idle"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "usage_risk_notifications",
        "description": "Send usage risk upgrade suggestions.",
        "schedule": "19,49 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_comm_campaigns",
        "description": "task_description.send_comm_campaigns",
        "schedule": "*/10 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

    # Communications are handled exclusively by send_expiration_emails and
    # send_comm_campaigns. Keep legacy data tables for migration/history, but
    # remove obsolete executable task rows from existing installations.
    cursor.execute(
        """
        DELETE FROM tasks
        WHERE name IN (
            'send_mail_campaigns',
            'send_campaign_discord',
            'send_expiration_discord'
        )
        """
    )
    conn.commit()

