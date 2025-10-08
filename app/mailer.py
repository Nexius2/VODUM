import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os
import sqlite3

from logger import logger
from config import DATABASE_PATH


def send_email(to, subject, body, attachment_path=None):
    """
    Envoie un email HTML (optionnellement avec pièce jointe) en utilisant les paramètres SMTP définis dans la base.
    """
    try:
        # 🔧 Lecture directe des paramètres SMTP depuis la table settings
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM settings LIMIT 1")
        row = cur.fetchone()
        conn.close()

        if not row:
            logger.error("❌ Aucune configuration SMTP trouvée dans la table settings.")
            return False, "Configuration SMTP manquante."

        smtp_server = row["smtp_host"]
        smtp_port = int(row["smtp_port"] or 587)
        smtp_user = row["smtp_user"]
        smtp_password = row["smtp_pass"]
        mail_from = row["mail_from"]

        if not smtp_server or not smtp_user or not smtp_password:
            logger.error("❌ Paramètres SMTP manquants : impossible d’envoyer l’email.")
            return False, "Paramètres SMTP manquants."

        # 📧 Construction du message (multipart si pièce jointe)
        if attachment_path:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "html"))
            try:
                with open(attachment_path, "rb") as f:
                    part = MIMEApplication(f.read())
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=os.path.basename(attachment_path),
                )
                msg.attach(part)
            except Exception as e:
                logger.error(f"❌ Erreur lecture pièce jointe: {e}")
                return False, f"Erreur lecture pièce jointe: {e}"
        else:
            msg = MIMEText(body, "html")

        msg["Subject"] = subject
        msg["From"] = mail_from
        msg["To"] = to

        # 🔐 Connexion SMTP sécurisée
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        logger.info(f"✅ Mail envoyé à {to} : {subject}")
        return True, None

    except Exception as e:
        logger.error(f"❌ Erreur lors de l’envoi du mail à {to} : {e}")
        return False, str(e)
