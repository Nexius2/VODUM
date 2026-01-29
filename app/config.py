import os

class Config:
    # Chemin vers la base SQLite (dans le conteneur)
    # Par défaut : /appdata/database.db
    DATABASE = os.environ.get("DATABASE_PATH", "/appdata/database.db")

    # Clé secrète Flask (change-la en prod)
    SECRET_KEY = os.environ.get("VODUM_SECRET_KEY", "change-me")

    # Mode debug (0/1)
    DEBUG = bool(int(os.environ.get("VODUM_DEBUG", "0")))


    # évite les collisions avec d'autres applis
    SESSION_COOKIE_NAME = os.environ.get("VODUM_SESSION_COOKIE_NAME", "vodum_session")

    # Optionnel mais conseillé
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("VODUM_SESSION_COOKIE_SAMESITE", "Lax")

    # Si tu es en HTTPS derrière proxy, mets à 1
    SESSION_COOKIE_SECURE = bool(int(os.environ.get("VODUM_SESSION_COOKIE_SECURE", "0")))