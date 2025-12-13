import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "/logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Logger global
logger = logging.getLogger("vodum")
logger.setLevel(logging.DEBUG)  # capture tout

# Rotating handler - 5 Mo max, 5 fichiers
handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5_000_000,
    backupCount=5,
    encoding="utf-8"
)

# Format clair
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
handler.setFormatter(formatter)

# Éviter les doublons
logger.addHandler(handler)          # On force l'ajout
logger.propagate = False            # On empêche la duplication dans stdout


def get_logger(name: str):
    """Retourne un logger enfant avec un nom distinct."""
    return logger.getChild(name)
