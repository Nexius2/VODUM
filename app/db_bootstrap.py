import sqlite3
import os

DB_PATH = "/appdata/database.db"

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
        placeholders = ", ".join("?" for _ in values)
        cursor.execute(
            f"INSERT INTO {table} ({fields}) VALUES ({placeholders})",
            tuple(values.values()),
        )


# ---------------------------------------------------------
# MIGRATIONS
# ---------------------------------------------------------

def run_migrations():
    print("🔧 Running DB migrations…")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # -------------------------------------------------
    # 1. Vérifier que toutes les tables existent
    # -------------------------------------------------

    REQUIRED_TABLES = {
        "vodum_users": [],
        "media_users": [],
        "servers": [],
        "libraries": [],
        "media_user_libraries": [],
        "email_templates": [],
        "sent_emails": [],
        "settings": [],
        "logs": [],
        "tasks": []
    }


    for table in REQUIRED_TABLES:
        if not table_exists(cursor, table):
            raise RuntimeError(f"❌ ERREUR : la table '{table}' n'existe pas ! "
                               f"-> Vérifie que tables.sql a été importé correctement.")

    print("✔ Toutes les tables existent.")

    # -------------------------------------------------
    # 2. Vérifier que toutes les colonnes obligatoires existent
    # -------------------------------------------------

    TASK_COLUMNS = {
        "name": "TEXT UNIQUE NOT NULL",
        "description": "TEXT",
        "schedule": "TEXT",
        "enabled": "INTEGER DEFAULT 1",
        "status": "TEXT",
        "last_run": "TIMESTAMP",
        "next_run": "TIMESTAMP",
        "last_error": "TEXT",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }

    for col, definition in TASK_COLUMNS.items():
        ensure_column(cursor, "tasks", col, definition)

    print("✔ Colonnes des tasks vérifiées.")

    # -------------------------------------------------
    # 3. Injecter les données par défaut
    # -------------------------------------------------

    # Tâche sync_plex
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "sync_plex",
        "description": "task_description.sync_plex",
        "schedule": "0 */6 * * *",  # toutes les 6h
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

    # Tâche backup automatique (tous les 3 jours à 03:00)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "auto_backup",
        "description": "task_description.auto_backup",
        "schedule": "0 3 */3 * *",   # tous les 3 jours
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

    # Tâche update_user_status
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "update_user_status",
        "description": "task_description.update_user_status",
        "schedule": "0 * * * *",  # Toutes les heures
        "enabled": 1,
        "status": "idle"
    })

    # Tâche check_servers (ping léger des serveurs toutes les 10 minutes)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "check_servers",
        "description": "task_description.check_servers",
        "schedule": "*/30 * * * *",  # toutes les 30 minutes
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

    # Ajouter la tâche send_expiration_emails si absente
    cursor.execute("""
        SELECT 1 FROM tasks WHERE name = 'send_expiration_emails'
    """)
    exists = cursor.fetchone()

    if not exists:
        cursor.execute("""
            INSERT INTO tasks (name, schedule, enabled, status)
            VALUES ('send_expiration_emails', '0 * * * *', 0, 'disabled')
        """)
        print("➕ Tâche send_expiration_emails ajoutée.")

    # -------------------------------------------------
    # 4. Templates email par défaut (anglais) si absents
    # -------------------------------------------------

    DEFAULT_TEMPLATES = {
        "preavis": {
            "subject": "Your subscription will expire soon",
            "body": (
                "Hello {username},\n\n"
                "Your subscription will expire in {days_left} days.\n"
                "Please renew it to avoid any service interruption.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Best regards,\n"
                "The VODUM Team"
            )
        },
        "relance": {
            "subject": "Reminder: Your subscription is about to expire",
            "body": (
                "Hello {username},\n\n"
                "This is a friendly reminder that your subscription will expire in {days_left} days.\n"
                "Don't forget to renew it in time.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Best regards,\n"
                "The VODUM Team"
            )
        },
        "fin": {
            "subject": "Your subscription has expired",
            "body": (
                "Hello {username},\n\n"
                "Your subscription expired on {expiration_date}.\n"
                "Your access has now been suspended.\n\n"
                "If you wish to continue using our services, you can renew your subscription at any time.\n\n"
                "Best regards,\n"
                "The VODUM Team"
            )
        }
    }

    for tpl_type, tpl_data in DEFAULT_TEMPLATES.items():

        # Vérifier existence du template
        cursor.execute(
            "SELECT COUNT(*) FROM email_templates WHERE type = ?",
            (tpl_type,)
        )
        exists = cursor.fetchone()[0]

        # Si inexistant → créer avec valeurs par défaut
        if exists == 0:
            print(f"➕ Ajout du template email par défaut : {tpl_type}")

            cursor.execute(
                """
                INSERT INTO email_templates (type, subject, body, days_before)
                VALUES (?, ?, ?, ?)
                """,
                (
                    tpl_type,
                    tpl_data["subject"],
                    tpl_data["body"],
                    30 if tpl_type == "preavis"
                    else 7 if tpl_type == "relance"
                    else 0

                ),
            )

        else:
            # Si existant → vérifier s'il manque subject / body
            cursor.execute(
                "SELECT subject, body FROM email_templates WHERE type = ?",
                (tpl_type,)
            )
            row = cursor.fetchone()

            # row est un tuple, pas un Row → utiliser indices
            subject = row[0] if row else ""
            body = row[1] if row else ""

            if not subject or not body:
                print(f"🛠 Mise à jour du template email vide : {tpl_type}")
                cursor.execute(
                    """
                    UPDATE email_templates
                    SET subject = CASE WHEN subject='' OR subject IS NULL THEN ? ELSE subject END,
                        body    = CASE WHEN body='' OR body IS NULL THEN ? ELSE body END
                    WHERE type = ?
                    """,
                    (
                        tpl_data["subject"],
                        tpl_data["body"],
                        tpl_type
                    )
                )

    # Tâche d'envoi des campagnes email
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "send_mail_campaigns",
        "description": "task_description.send_campaign_emails",
        "schedule": "*/5 * * * *",  # toutes les 5 minutes
        "enabled": 0,
        "status": "disabled"
    })

    # Tâche check_mailing_status : vérifie chaque heure l'activation du mailing
    #ensure_row(cursor, "tasks", "name = :name", {
    #    "name": "check_mailing_status",
    #    "description": "Vérifie le paramètre mailing_enabled et active/désactive les tâches d'envoi",
    #    "schedule": "*/5 * * * *",  # toutes les 5 minutes
    #    "enabled": 1,
    #    "status": "idle"
    #})

    # Tâche apply_plex_access_updates (pour appliquer les jobs Plex)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_plex_access_updates",
        "description": "task_description.apply_plex_access_updates",
        "schedule": "*/2 * * * *",   # toutes les 2 minutes
        "enabled": 0,                # activée uniquement quand un job est ajouté
        "status": "idle"
    })

    # Tâche sync_Jellyfin
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "sync_jellyfin",
        "description": "task_description.sync_jellyfin_users",
        "schedule": "0 */6 * * *",  # toutes les 6 heures (comme Plex)
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

    # Tâche apply_jellyfin_access_updates (désactivation des accès Jellyfin à l'expiration)
    ensure_row(cursor, "tasks", "name = :name", {
        "name": "apply_jellyfin_access_updates",
        "description": "task_description.apply_jellyfin_access_updates",
        "schedule": "*/2 * * * *",   # toutes les 2 minutes
        "enabled": 0,
        "status": "idle"
    })




    # -------------------------------------------------
    # Paramètres de base (settings)
    # -------------------------------------------------

    ensure_row(cursor, "settings", "id = :id", {
        "id": 1,
        "mail_from": "noreply@example.com",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_tls": 1,
        "smtp_user": "",
        "smtp_pass": "",

        # ⛔ NE PAS FORCER LA LANGUE
        "default_language": None,

        "timezone": "Europe/Paris",
        "admin_email": "",
        "enable_cron_jobs": 1,
        "default_expiration_days": 90,
        "maintenance_mode": 0,
        "debug_mode": 0
    })




    conn.commit()
    conn.close()

    print("✔ Migrations terminées avec succès !")








if __name__ == "__main__":
    run_migrations()
    #ensure_settings_defaults(cursor)

