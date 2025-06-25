import sqlite3
import time
from datetime import datetime, timedelta
from mailer import send_email
from config import DATABASE_PATH
from settings_helper import get_settings
from logger import logger
#from app import update_task_status


UPDATE_INTERVAL = 86400

class SafeDict(dict):
    def __missing__(self, key):
        return ""


def load_templates():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT type, subject, body, days_before FROM email_templates")
    templates = {row[0]: {"subject": row[1], "body": row[2], "days_before": row[3]} for row in cursor.fetchall()}
    conn.close()
    return templates


def get_users():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE expiration_date IS NOT NULL")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users


def should_send(days_left, template_days):
    return 0 <= days_left <= template_days


def already_sent(user_id, mail_type, expiration_date):
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
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM locks WHERE name = 'reminder_lock'")
    conn.commit()
    conn.close()


def auto_reminders():
    if not acquire_lock():
        logger.warning("🔒 Un autre processus gère déjà l'envoi des rappels. Abandon.")
        return
        
    while True:
        settings = get_settings()
        if not settings.get("send_reminders"):
            logger.info("⏸️ Envoi de mails désactivé dans les paramètres.")
            time.sleep(UPDATE_INTERVAL)
            continue

        templates = load_templates()
        today = datetime.now().date()
        logger.info("⏸️ Envoi des mails pour les abonnements expirés ou bientôt expirés.")


        for user in get_users():
            if not user.get("email"):
                continue

            try:
                expiration_date = datetime.strptime(user["expiration_date"], "%Y-%m-%d").date()
                days_left = (expiration_date - today).days
                #logger.info(f"👀 {user['username']} expire dans {days_left} jours – checking {mail_type} (J-{tpl['days_before']})")

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
                    #subject = tpl["subject"].replace("{{username}}", user["username"])
                    subject = tpl["subject"].format_map(SafeDict({
                        "username": user.get("username", ""),
                        "days_left": days_left
                    }))

                    #body = tpl["body"].replace("{{username}}", user["username"])
                    body = tpl["body"].format_map(SafeDict({
                        "username": user.get("username", ""),
                        "days_left": days_left
                    }))

                    #success = send_email(user["email"], subject, body)
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
                        time.sleep(30)  # ⏱️ Pause de 30 secondes entre chaque mail

        release_lock()
        update_task_status("send_reminders", UPDATE_INTERVAL)  # 24h
        time.sleep(UPDATE_INTERVAL)

def update_task_status(task_name, interval_seconds):
    from config import DATABASE_PATH
    now = datetime.now()
    next_run = now + timedelta(seconds=interval_seconds)
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO task_status (name, last_run, next_run)
        VALUES (?, ?, ?)
    """, (task_name, now.isoformat(), next_run.isoformat()))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    auto_reminders()
    main()
