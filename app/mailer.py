import smtplib
from email.mime.text import MIMEText
from settings_helper import get_settings
from logger import logger


def send_email(to, subject, body):
    settings = get_settings()

    msg = MIMEText(body, "html")
    msg["Subject"] = subject
    msg["From"] = settings["mail_from"]
    msg["To"] = to

    try:
        server = smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=10)
        if settings["smtp_tls"]:
            server.starttls()
        server.login(settings["smtp_user"], settings["smtp_pass"])
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())
        server.quit()
        logger.info(f"📧 Mail envoyé à {to}")
        return True, f"📧 Mail envoyé à {to}"
    except Exception as e:
        #error_msg = f"❌ Erreur envoi mail à {to} : {e}"
        logger.error(f"❌ Erreur envoi mail à {to} : {e}")
        return False, str(e)
