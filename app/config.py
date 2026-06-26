import os
import secrets
from datetime import timedelta
from pathlib import Path

from db_manager import open_sqlite_connection


def _get_secret_key() -> str:
    """
    Ordre de prioritÃ© :
    1. VODUM_SECRET_KEY (env)
    2. fichier local persistant Ã  cÃ´tÃ© de la BDD
    3. gÃ©nÃ©ration auto + Ã©criture dans le fichier
    """
    env_key = (os.environ.get("VODUM_SECRET_KEY") or "").strip()
    if env_key:
        return env_key

    db_path = os.environ.get("DATABASE_PATH", "/appdata/database.db")
    default_key_file = str(Path(db_path).resolve().parent / "vodum.secret_key")
    key_file = Path(os.environ.get("VODUM_SECRET_KEY_FILE", default_key_file))

    try:
        if key_file.exists():
            value = key_file.read_text(encoding="utf-8").strip()
            if value:
                return value
    except Exception:
        pass

    secret_key = secrets.token_hex(32)

    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(secret_key, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
    except Exception:
        return secret_key

    return secret_key


def _read_settings_from_db(db_path: str) -> dict:
    conn = None
    try:
        conn = open_sqlite_connection(db_path, read_only=True)
        row = conn.execute(
            """
            SELECT web_secure_cookies, web_cookie_samesite
            FROM settings
            WHERE id = 1
            """
        ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}
    finally:
        if conn is not None:
            conn.close()


def _get_session_cookie_secure(db_path: str) -> bool:
    env_value = os.environ.get("VODUM_SESSION_COOKIE_SECURE")
    if env_value is not None:
        return str(env_value).strip() in ("1", "true", "True", "yes", "YES")

    settings = _read_settings_from_db(db_path)
    try:
        return int(settings.get("web_secure_cookies") or 0) == 1
    except Exception:
        return False


def _get_session_cookie_samesite(db_path: str) -> str:
    env_value = (os.environ.get("VODUM_SESSION_COOKIE_SAMESITE") or "").strip()
    if env_value:
        value = env_value
    else:
        settings = _read_settings_from_db(db_path)
        value = (settings.get("web_cookie_samesite") or "Lax").strip()

    if value not in ("Lax", "Strict", "None"):
        value = "Lax"

    return value


class Config:
    # Chemin vers la base SQLite (dans le conteneur)
    DATABASE = os.environ.get("DATABASE_PATH", "/appdata/database.db")
    DATABASE_PATH = DATABASE

    # Secret key auto-gÃ©nÃ©rÃ©e/persistÃ©e
    SECRET_KEY = _get_secret_key()

    # Mode debug (0/1)
    DEBUG = bool(int(os.environ.get("VODUM_DEBUG", "0")))

    # Limit the complete HTTP request body, including uploaded backups.
    MAX_CONTENT_LENGTH = max(
        1,
        int(os.environ.get("VODUM_MAX_UPLOAD_MB", "4096")),
    ) * 1024 * 1024

    # Ã©vite les collisions avec d'autres applis
    SESSION_COOKIE_NAME = os.environ.get("VODUM_SESSION_COOKIE_NAME", "vodum_session")

    # session cookie
    SESSION_COOKIE_HTTPONLY = True
    _SESSION_COOKIE_SAMESITE = _get_session_cookie_samesite(DATABASE)
    SESSION_COOKIE_SAMESITE = _SESSION_COOKIE_SAMESITE

    # Si SameSite=None, Secure doit Ãªtre forcÃ© sinon le cookie sera rejetÃ© par les navigateurs modernes
    SESSION_COOKIE_SECURE = _get_session_cookie_secure(DATABASE) or _SESSION_COOKIE_SAMESITE == "None"

    # session admin
    PERMANENT_SESSION_LIFETIME = timedelta(
        hours=max(1, int(os.environ.get("VODUM_SESSION_LIFETIME_HOURS", "12")))
    )
    SESSION_REFRESH_EACH_REQUEST = True


