from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


SECRET_PREFIX = "enc:v1:"


class SecretDecryptionError(ValueError):
    pass


def _key_file_path() -> Path:
    configured = (os.environ.get("VODUM_ENCRYPTION_KEY_FILE") or "").strip()
    if configured:
        return Path(configured)

    db_path = Path(os.environ.get("DATABASE_PATH", "/appdata/database.db")).resolve()
    return db_path.parent / "vodum.encryption_key"


def encryption_key_file_path() -> Path:
    return _key_file_path()


def encryption_key_bytes() -> bytes:
    return _load_or_create_key()


def validate_encryption_key(key_bytes: bytes, *, check_environment: bool = False) -> None:
    try:
        Fernet(key_bytes)
    except Exception as exc:
        raise SecretDecryptionError("Invalid Vodum encryption key backup") from exc

    if check_environment:
        env_key = (os.environ.get("VODUM_ENCRYPTION_KEY") or "").strip()
        if env_key and env_key.encode("ascii") != key_bytes:
            raise SecretDecryptionError(
                "The backup uses a different encryption key than "
                "VODUM_ENCRYPTION_KEY. Update or remove that environment variable "
                "before restoring this backup."
            )


def install_encryption_key(key_bytes: bytes) -> Path:
    validate_encryption_key(key_bytes, check_environment=True)

    key_file = _key_file_path()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = key_file.with_name(key_file.name + ".restore_tmp")
    tmp_file.write_bytes(key_bytes)
    try:
        os.chmod(tmp_file, 0o600)
    except OSError:
        pass
    os.replace(tmp_file, key_file)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key_file


def _load_or_create_key() -> bytes:
    env_key = (os.environ.get("VODUM_ENCRYPTION_KEY") or "").strip()
    if env_key:
        return env_key.encode("ascii")

    key_file = _key_file_path()
    try:
        existing = key_file.read_text(encoding="ascii").strip()
        if existing:
            return existing.encode("ascii")
    except FileNotFoundError:
        pass

    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key.decode("ascii"), encoding="ascii")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    try:
        return Fernet(_load_or_create_key())
    except Exception as exc:
        raise SecretDecryptionError(
            "Invalid or unavailable VODUM encryption key"
        ) from exc


def is_encrypted_secret(value: object) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_PREFIX)


def encrypt_secret(value: object) -> str | None:
    if value is None:
        return None

    text = str(value)
    if not text or is_encrypted_secret(text):
        return text

    token = _fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return SECRET_PREFIX + token


def decrypt_secret(value: object) -> str | None:
    if value is None:
        return None

    text = str(value)
    if not is_encrypted_secret(text):
        return text

    token = text[len(SECRET_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise SecretDecryptionError(
            "Unable to decrypt a stored Vodum secret. Check the encryption key."
        ) from exc


def decrypt_communication_settings(settings: dict | None) -> dict:
    result = dict(settings or {})
    for key in ("smtp_pass", "discord_bot_token", "discord_bot_token_effective"):
        if key in result:
            result[key] = decrypt_secret(result.get(key))
    return result


def _transform_tautulli_api_key(settings_json: object, transform) -> str | None:
    if settings_json is None:
        return None

    text = str(settings_json)
    if not text:
        return text

    try:
        settings = json.loads(text)
    except (TypeError, ValueError):
        return text

    if not isinstance(settings, dict):
        return text

    tautulli = settings.get("tautulli")
    if not isinstance(tautulli, dict) or "api_key" not in tautulli:
        return text

    transformed = transform(tautulli.get("api_key"))
    if transformed == tautulli.get("api_key"):
        return text

    tautulli["api_key"] = transformed
    return json.dumps(settings)


def encrypt_server_settings_json(settings_json: object) -> str | None:
    return _transform_tautulli_api_key(settings_json, encrypt_secret)


def keep_existing_secret(submitted: object, existing: object) -> str | None:
    if submitted is None or not str(submitted).strip():
        return str(existing) if existing is not None else None
    return str(submitted).strip()


def decrypt_server_settings_json(settings_json: object) -> str | None:
    return _transform_tautulli_api_key(settings_json, decrypt_secret)


def decrypt_server_record(record) -> dict:
    result = dict(record or {})
    if "token" in result:
        result["token"] = decrypt_secret(result.get("token"))
    if "settings_json" in result:
        result["settings_json"] = decrypt_server_settings_json(
            result.get("settings_json")
        )
    return result


def find_plex_servers_by_token(db, token: object) -> list[dict]:
    expected = str(token or "")
    if not expected:
        return []

    matches = []
    for row in db.query(
        "SELECT * FROM servers WHERE type='plex' ORDER BY name ASC"
    ):
        server = decrypt_server_record(row)
        candidate = str(server.get("token") or "")
        if candidate and hmac.compare_digest(candidate, expected):
            matches.append(server)
    return matches


def find_plex_server_ids_by_token(db, token: object) -> list[int]:
    return [int(server["id"]) for server in find_plex_servers_by_token(db, token)]


def encrypt_communication_secrets(conn) -> int:
    updated = 0

    row = conn.execute(
        "SELECT smtp_pass, discord_bot_token FROM settings WHERE id = 1"
    ).fetchone()
    if row:
        smtp_pass = encrypt_secret(row[0])
        discord_token = encrypt_secret(row[1])
        if smtp_pass != row[0] or discord_token != row[1]:
            conn.execute(
                """
                UPDATE settings
                SET smtp_pass = ?, discord_bot_token = ?
                WHERE id = 1
                """,
                (smtp_pass, discord_token),
            )
            updated += 1

    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='discord_bots'"
    ).fetchone()
    if table_exists:
        rows = conn.execute("SELECT id, token FROM discord_bots").fetchall()
        for bot_id, token in rows:
            encrypted = encrypt_secret(token)
            if encrypted != token:
                conn.execute(
                    "UPDATE discord_bots SET token = ? WHERE id = ?",
                    (encrypted, bot_id),
                )
                updated += 1

    return updated


def encrypt_server_secrets(conn) -> int:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='servers'"
    ).fetchone()
    if not table_exists:
        return 0

    updated = 0
    rows = conn.execute("SELECT id, token, settings_json FROM servers").fetchall()
    for server_id, token, settings_json in rows:
        encrypted_token = encrypt_secret(token)
        encrypted_settings = encrypt_server_settings_json(settings_json)
        if encrypted_token != token or encrypted_settings != settings_json:
            conn.execute(
                "UPDATE servers SET token = ?, settings_json = ? WHERE id = ?",
                (encrypted_token, encrypted_settings, server_id),
            )
            updated += 1

    return updated
