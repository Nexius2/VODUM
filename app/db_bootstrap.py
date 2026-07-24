import os
import sys
from db_manager import open_sqlite_connection
from core.db_bootstrap_monitoring import ensure_import_monitoring_schema
from core.db_bootstrap_migrations import ensure_migration_foundation_schema
from core.db_bootstrap_tasks import migrate_task_scheduler_mode
from core.db_bootstrap_core import validate_and_upgrade_core_schema
from core.db_bootstrap_usage_risk import ensure_usage_risk_schema
from core.db_bootstrap_referrals import ensure_referral_schema
from core.db_bootstrap_referral_events import ensure_referral_event_schema
from core.db_bootstrap_users import upgrade_vodum_user_schema
from core.db_bootstrap_subscriptions import ensure_subscription_template_schema
from core.db_bootstrap_settings import upgrade_task_settings_auth_schema
from core.db_bootstrap_streams import ensure_stream_enforcement_schema
from core.db_bootstrap_welcome import ensure_welcome_template_schema, seed_welcome_templates
from core.db_bootstrap_discord import ensure_discord_schema
from core.db_bootstrap_subscription_gifts import ensure_subscription_gift_schema
from core.db_bootstrap_monitoring_history import ensure_monitoring_history_schema
from core.db_bootstrap_monitoring_live import ensure_monitoring_live_schema
from core.db_bootstrap_media_jobs import upgrade_media_jobs_schema
from core.db_bootstrap_media_types import normalize_monitoring_media_types
from core.db_bootstrap_query_indexes import ensure_application_query_indexes
from core.db_bootstrap_task_defaults import migrate_task_schedule_defaults
from core.db_bootstrap_cron_control import enforce_global_cron_setting
from core.db_bootstrap_usage_risk_template import ensure_usage_risk_template
from core.db_bootstrap_base_settings import ensure_base_settings
from core.db_bootstrap_secret_migration import migrate_plaintext_secrets
from core.db_bootstrap_comm_defaults import seed_default_comm_templates
from core.db_bootstrap_email_defaults import seed_legacy_email_templates
from core.db_bootstrap_communications import ensure_communications_schema
from core.db_bootstrap_task_catalog import seed_default_tasks


# Bootstrap messages contain Unicode symbols. Some host consoles (notably
# Windows cp1252) cannot encode them and used to abort before opening the DB.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

DB_PATH = os.environ.get("DATABASE_PATH", "/appdata/database.db")

# ---------------------------------------------------------
# Utility: checks
# ---------------------------------------------------------

def table_exists(cursor, table):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def ensure_column(cursor, table, column, definition):
    if not column_exists(cursor, table, column):
        print(f"🛠 Ajout de la colonne manquante : {table}.{column}")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def ensure_row(cursor, table, where_clause, values):
    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}", values)
    if cursor.fetchone()[0] == 0:
        fields = ", ".join(values.keys())
        placeholders = ", ".join(["?"] * len(values))
        cursor.execute(
            f"INSERT INTO {table} ({fields}) VALUES ({placeholders})",
            tuple(values.values()),
        )


# ---------------------------------------------------------
# MIGRATIONS
# ---------------------------------------------------------

def run_migrations():
    print("🔧 Running DB migrations…")

    conn = open_sqlite_connection(DB_PATH)
    cursor = conn.cursor()

    # -------------------------------------------------
    # 0. Nettoyage legacy : suppression table logs (désormais obsolète)
    # -------------------------------------------------
    if table_exists(cursor, "logs"):
        print("🧹 Dropping legacy table: logs")
        cursor.execute("DROP TABLE IF EXISTS logs")
        conn.commit()

    ensure_welcome_template_schema(conn, cursor, table_exists=table_exists)

    ensure_stream_enforcement_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )

    ensure_import_monitoring_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )

    ensure_migration_foundation_schema(conn, cursor)

    migrate_task_scheduler_mode(
        conn,
        cursor,
        ensure_column=ensure_column,
    )

    validate_and_upgrade_core_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )

    ensure_usage_risk_schema(
        conn,
        cursor,
        table_exists=table_exists,
    )

    ensure_referral_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
        ensure_row=ensure_row,
    )

    ensure_referral_event_schema(
        conn,
        cursor,
        table_exists=table_exists,
    )

    print("✔ All tables exist.")

    upgrade_vodum_user_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )


    ensure_subscription_template_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )




    upgrade_task_settings_auth_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )

    ensure_discord_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )

    # -------------------------------------------------
    ensure_communications_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )



    ensure_subscription_gift_schema(conn, cursor, table_exists=table_exists)

    ensure_monitoring_live_schema(conn, cursor, table_exists=table_exists)

    ensure_monitoring_history_schema(
        conn,
        cursor,
        table_exists=table_exists,
        ensure_column=ensure_column,
    )

    upgrade_media_jobs_schema(
        conn,
        cursor,
        table_exists=table_exists,
        column_exists=column_exists,
        ensure_column=ensure_column,
    )

    normalize_monitoring_media_types(conn, cursor)

    # Includes the documented referral traversal index
    # idx_user_referrals_status_start (see tools/validate_query_plans.py).
    ensure_application_query_indexes(conn, cursor)


    # -------------------------------------------------
    seed_default_tasks(conn, cursor, ensure_row=ensure_row)



    enforce_global_cron_setting(conn, cursor)


    seed_welcome_templates(conn, cursor)

    seed_default_comm_templates(conn, cursor)


    seed_legacy_email_templates(conn, cursor)


    # Tâche check_mailing_status : active/désactive automatiquement les tâches Email/Discord
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_mailing_status",
        "description": "task_description.check_mailing_status",
        "schedule": "9 * * * *",  # toutes les heures, hors minute de pointe
        "enabled": 1,
        "status": "idle"
    })


    # Tâche stream_enforcer
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "stream_enforcer",
        "description": "task_description.stream_enforcer",
        "schedule": "*/2 * * * *",   # toutes les 2 minutes
        "enabled": 0,
        "status": "disabled"
    })

    # Tâche apply_plex_access_updates (pour appliquer les jobs Plex)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_plex_access_updates",
        "description": "task_description.apply_plex_access_updates",
        "schedule": "*/5 * * * *",   # toutes les 5 minutes
        "enabled": 0,                # activée uniquement quand un job est ajouté
        "status": "idle"
    })

    # Tâche sync_Jellyfin
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "sync_jellyfin",
        "description": "task_description.sync_jellyfin",
        "schedule": "17 */6 * * *",  # toutes les 6 heures, après Plex
        "enabled": 0,
        "status": "disabled"
    })

    # Tâche disable_expired_users (désactivation des accès Plex à l'expiration)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "disable_expired_users",
        "description": "task_description.disable_expired_users",
        "schedule": "0 */12 * * *",  # toutes les 12 heures
        "enabled": 0,                # pilotée par settings.disable_on_expiry
        "status": "idle"
    })
    # Tâche expired_subscription_manager (policy "abonnement expiré" + disable différé)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "expired_subscription_manager",
        "description": "task_description.expired_subscription_manager",
        "schedule": "13 * * * *",  # toutes les heures, hors minute de pointe
        "enabled": 0,               # pilotée par settings.expiry_mode
        "status": "disabled"
    })



    # Tâche apply_jellyfin_access_updates (désactivation des accès Jellyfin à l'expiration)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_jellyfin_access_updates",
        "description": "task_description.apply_jellyfin_access_updates",
        "schedule": "*/5 * * * *",   # toutes les 5 minutes
        "enabled": 0,
        "status": "idle"
    })

    # Tâche legacy monitor_collect_sessions
    #
    # Cette ancienne tâche collecte tous les serveurs en direct.
    # Elle ne doit plus tourner avec le nouveau pipeline :
    # monitor_enqueue_refresh -> media_jobs_worker -> collect_sessions_for_server.
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "monitor_collect_sessions",
        "description": "task_description.monitor_collect_sessions",
        "schedule": None,
        "enabled": 0,
        "status": "disabled"
    })

    ensure_row(cursor, "tasks", "name = :name", {
        "name": "migration_worker",
        "description": "task_description.migration_worker",
        "schedule": "*/2 * * * *",
        "enabled": 0,
        "status": "disabled"
    })

    cursor.execute("""
        UPDATE tasks
        SET enabled = 0,
            status = 'disabled',
            schedule = NULL,
            queued_count = 0,
            next_run = NULL
        WHERE name = 'monitor_collect_sessions'
    """)

    # Tâche refresh_dashboard_quote_cache (quote du jour du dashboard)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "refresh_dashboard_quote_cache",
        "description": "task_description.refresh_dashboard_quote_cache",
        "schedule": "*/3 * * * *",   # vérifie toutes les 3h, mais ne recalcule qu'une fois par jour
        "enabled": 1,
        "status": "idle"
    })

    # Auto-réparation :
    # si la tâche existe déjà mais est restée désactivée sur une ancienne base,
    # on la remet ON uniquement si elle n'a encore jamais tourné.
    cursor.execute(
        """
        UPDATE tasks
        SET
            enabled = 1,
            status = 'idle',
            updated_at = CURRENT_TIMESTAMP
        WHERE name = 'refresh_dashboard_quote_cache'
          AND COALESCE(enabled, 0) = 0
          AND last_run IS NULL
        """
    )

    # Tâche referral rewards
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "process_referral_rewards",
        "description": "task_description.process_referral_rewards",
        "schedule": "15 2 * * *",
        "enabled": 1,
        "status": "idle",
    })
    # Tâche referral_cleanup
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "referral_cleanup",
        "description": "task_description.referral_cleanup",
        "schedule": "0 12 * * *",
        "enabled": 1,
        "status": "idle"
    })
    conn.commit()

    ensure_base_settings(conn, cursor, ensure_row=ensure_row)
    migrate_plaintext_secrets(conn)

    migrate_task_schedule_defaults(conn, cursor)

    ensure_usage_risk_template(conn, cursor)

    conn.commit()
    conn.close()

    print("✔ Migrations completed successfully !")



if __name__ == "__main__":
    run_migrations()
    #ensure_settings_defaults(cursor)
