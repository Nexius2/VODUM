import sqlite3
import time
from datetime import datetime, timedelta
from mailer import send_email
from config import DATABASE_PATH
from settings_helper import get_settings
from logger import logger

# Intervalle avant nouvel envoi (non utilisé, laissé pour compatibilité éventuelle)
UPDATE_INTERVAL = 86400  # 24h

class SafeDict(dict):
    def __missing__(self, key):
        return ""

def load_templates():
    """Charge les modèles d'email depuis la base."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT type, subject, body, days_before FROM email_templates")
    templates = {row[0]: {"subject": row[1], "body": row[2], "days_before": row[3]} for row in cursor.fetchall()}
    conn.close()
    return templates

def get_users():
    """Récupère tous les utilisateurs éligibles à un mail (hors 'unfriended')."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM users
        WHERE expiration_date IS NOT NULL
          AND status != 'unfriended'
          AND COALESCE(TRIM(email), '') <> ''   -- évite les adresses vides
    """)
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users


def should_send(days_left, template_days):
    """Détermine si le mail doit être envoyé selon le nombre de jours restants."""
    return 0 <= days_left <= template_days

def already_sent(user_id, mail_type, expiration_date):
    """Vérifie si le mail a déjà été envoyé pour ce type et cette date d'expiration."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1 FROM sent_emails
        WHERE user_id = ? AND type = ? AND expiration_snapshot = ?
        LIMIT 1
    """, (user_id, mail_type, expiration_date))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def acquire_lock():
    """Empêche l’exécution concurrente (pour éviter les doublons d’envois)."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO locks (name, acquired_at) VALUES ('reminder_lock', ?)", (datetime.now().isoformat(),))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def release_lock():
    """Libère le verrou."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM locks WHERE name = 'reminder_lock'")
    conn.commit()
    conn.close()

def auto_reminders():
    """
    Fonction principale : envoie les mails de rappel aux utilisateurs selon leur date d’expiration.
    À lancer une seule fois (mode cron/Supercronic).
    """
    if not acquire_lock():
        logger.warning("🔒 Un autre processus gère déjà l'envoi des rappels. Abandon.")
        return

    settings = get_settings()
    if not settings.get("send_reminders"):
        logger.info("⏸️ Envoi de mails désactivé dans les paramètres.")
        release_lock()
        return

    templates = load_templates()
    today = datetime.now().date()
    logger.info("⏸️ Envoi des mails pour les abonnements expirés ou bientôt expirés.")

    for user in get_users():
        if not user.get("email"):
            continue
        if (user.get("status") or "") == "unfriended":
            continue

        try:
            expiration_date = datetime.strptime(user["expiration_date"], "%Y-%m-%d").date()
            days_left = (expiration_date - today).days
        except Exception as e:
            logger.warning(f"⚠️ Utilisateur {user['id']} : date invalide → {e}")
            continue

        for mail_type in ["preavis", "relance", "fin"]:
            tpl = templates.get(mail_type)
            if not tpl:
                continue
            logger.debug(f"👀 {user['username']} expire dans {days_left} jours – checking {mail_type} (J-{tpl['days_before']})")

            date_str = today.isoformat()
            if already_sent(user["id"], mail_type, user["expiration_date"]):
                logger.info(f"📭 Mail déjà envoyé ({mail_type}) à {user['username']} aujourd’hui")
                continue

            if should_send(days_left, tpl["days_before"]):
                subject = tpl["subject"].format_map(SafeDict({
                    "username": user.get("username", ""),
                    "days_left": days_left
                }))

                body = tpl["body"].format_map(SafeDict({
                    "username": user.get("username", ""),
                    "days_left": days_left
                }))

                emails = [user["email"]]
                if user.get("second_email"):
                    emails.append(user["second_email"])

                success = True
                for e in emails:
                    s, _ = send_email(e, subject, body)
                    success = success and s

                if success:
                    logger.info(f"📧 Mail '{mail_type}' envoyé à {user['email']} ({user['username']})")
                    conn = sqlite3.connect(DATABASE_PATH)
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO sent_emails (user_id, type, date_sent, expiration_snapshot)
                        VALUES (?, ?, ?, ?)
                    """, (user["id"], mail_type, date_str, user["expiration_date"]))
                    conn.commit()
                    conn.close()
                    time.sleep(30)  # Pause anti-spam

    release_lock()
    update_task_status("send_reminders")  # Tu peux ajouter le champ 'interval' si tu le souhaites

def update_task_status(task_name):
    """Met à jour la table de suivi pour l’historique des envois."""
    now = datetime.now()
    next_run = None
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO task_status (name, last_run, next_run)
        VALUES (?, ?, ?)
    """, (task_name, now.isoformat(), next_run))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    auto_reminders()
