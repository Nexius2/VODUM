from __future__ import annotations

import hashlib
import ipaddress
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

LOCAL_TOTP_COOKIE_NAME = "vodum_local_2fa_trust"
LOCAL_TOTP_TRUST_DAYS = 30
LOCAL_TOTP_TRUST_SECONDS = LOCAL_TOTP_TRUST_DAYS * 24 * 60 * 60


def is_local_client_ip(ip_value: str | None) -> bool:
    try:
        ip = ipaddress.ip_address((ip_value or "").strip())
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def _secret_fingerprint(stored_totp_secret: Any) -> str:
    text = str(stored_totp_secret or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(str(secret_key or ""), salt="vodum-local-2fa-trust")


def make_local_totp_trust_token(secret_key: str, admin_email: str, stored_totp_secret: Any) -> str:
    payload = {
        "email": (admin_email or "").strip().lower(),
        "totp": _secret_fingerprint(stored_totp_secret),
    }
    return _serializer(secret_key).dumps(payload)


def is_valid_local_totp_trust(
    *,
    secret_key: str,
    admin_email: str,
    stored_totp_secret: Any,
    client_ip: str | None,
    token: str | None,
) -> bool:
    if not token or not is_local_client_ip(client_ip):
        return False

    try:
        payload = _serializer(secret_key).loads(token, max_age=LOCAL_TOTP_TRUST_SECONDS)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return False

    if not isinstance(payload, dict):
        return False

    return (
        payload.get("email") == (admin_email or "").strip().lower()
        and payload.get("totp") == _secret_fingerprint(stored_totp_secret)
    )


def set_local_totp_trust_cookie(response, *, secret_key: str, admin_email: str, stored_totp_secret: Any, secure: bool) -> None:
    token = make_local_totp_trust_token(secret_key, admin_email, stored_totp_secret)
    response.set_cookie(
        LOCAL_TOTP_COOKIE_NAME,
        token,
        max_age=LOCAL_TOTP_TRUST_SECONDS,
        httponly=True,
        secure=bool(secure),
        samesite="Lax",
    )