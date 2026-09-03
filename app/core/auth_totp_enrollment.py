from __future__ import annotations

import time
from typing import MutableMapping

from core.auth_totp import generate_totp_secret


TOTP_ENROLLMENT_SESSION_KEY = "vodum_totp_enrollments"
TOTP_ENROLLMENT_MAX_AGE_SECONDS = 10 * 60
_ALLOWED_PURPOSES = {"settings", "setup"}


def _purpose(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ALLOWED_PURPOSES:
        raise ValueError("unsupported TOTP enrollment purpose")
    return normalized


def get_or_begin_totp_enrollment(
    session_store: MutableMapping,
    *,
    purpose: str,
    now: int | None = None,
) -> str:
    normalized = _purpose(purpose)
    current_time = int(time.time() if now is None else now)
    enrollments = session_store.get(TOTP_ENROLLMENT_SESSION_KEY)
    enrollments = dict(enrollments) if isinstance(enrollments, dict) else {}
    pending = enrollments.get(normalized)
    if isinstance(pending, dict):
        try:
            age = current_time - int(pending["started_at"])
            secret = str(pending["secret"])
        except (KeyError, TypeError, ValueError):
            age, secret = -1, ""
        if secret and 0 <= age <= TOTP_ENROLLMENT_MAX_AGE_SECONDS:
            return secret

    secret = generate_totp_secret()
    enrollments[normalized] = {"secret": secret, "started_at": current_time}
    session_store[TOTP_ENROLLMENT_SESSION_KEY] = enrollments
    return secret


def consume_totp_enrollment(
    session_store: MutableMapping,
    *,
    purpose: str,
    now: int | None = None,
) -> str:
    normalized = _purpose(purpose)
    current_time = int(time.time() if now is None else now)
    enrollments = session_store.get(TOTP_ENROLLMENT_SESSION_KEY)
    enrollments = dict(enrollments) if isinstance(enrollments, dict) else {}
    pending = enrollments.pop(normalized, None)
    if enrollments:
        session_store[TOTP_ENROLLMENT_SESSION_KEY] = enrollments
    else:
        session_store.pop(TOTP_ENROLLMENT_SESSION_KEY, None)
    if not isinstance(pending, dict):
        return ""
    try:
        age = current_time - int(pending["started_at"])
        secret = str(pending["secret"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not secret or age < 0 or age > TOTP_ENROLLMENT_MAX_AGE_SECONDS:
        return ""
    return secret
