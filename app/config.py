import os

class Config:
    # Chemin vers la base SQLite (dans le conteneur)
    # Par défaut : /appdata/database.db
    DATABASE = os.environ.get("DATABASE_PATH", "/appdata/database.db")

    # Clé secrète Flask (change-la en prod)
    SECRET_KEY = os.environ.get("VODUM_SECRET_KEY", "change-me")

    # Mode debug (0/1)
    DEBUG = bool(int(os.environ.get("VODUM_DEBUG", "0")))
