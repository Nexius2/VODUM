import logging
from logging.handlers import RotatingFileHandler
import os

# Création du dossier logs si besoin
LOG_DIR = "/app/appdata/logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Formatter personnalisé pour forcer une seule ligne
class SingleLineFormatter(logging.Formatter):
    def format(self, record):
        if record.args:
            record.msg = str(record.msg).replace("\n", " ").replace("\r", " ")
        else:
            record.msg = record.msg.replace("\n", " ").replace("\r", " ")
        return super().format(record).replace("\n", " ").replace("\r", " ").strip()



# Logger configuré
logger = logging.getLogger()  # logger racine
logger.setLevel(logging.DEBUG)

# Handler fichier
handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)

formatter = SingleLineFormatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
handler.setLevel(logging.DEBUG)
logger.debug("🧪 DEBUG activé dans logger.py")


# Console
console = logging.StreamHandler()
console.setFormatter(formatter)
console.setLevel(logging.DEBUG)

# Ajout des handlers (une seule fois)
#if not logger.hasHandlers():
logger.addHandler(handler)
logger.addHandler(console)
