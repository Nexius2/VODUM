from __future__ import annotations

import base64
import binascii
import hmac
import os
import struct
import time
from hashlib import sha1
from urllib.parse import quote


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _normalize_secret(secret: str) -> str:
    return "".join(str(secret or "").strip().upper().split())


def _totp_at(secret: str, counter: int, digits: int = 6) -> str:
    normalized = _normalize_secret(secret)
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def verify_totp_code(secret: str, code: str, *, now: int | None = None, step: int = 30, window: int = 1) -> bool:
    submitted = "".join(str(code or "").split())
    if not submitted.isdigit() or len(submitted) != 6:
        return False

    if now is None:
        now = int(time.time())

    counter = now // step
    try:
        for offset in range(-window, window + 1):
            expected = _totp_at(secret, counter + offset)
            if hmac.compare_digest(expected, submitted):
                return True
    except (binascii.Error, ValueError, TypeError):
        return False
    return False


def provisioning_uri(secret: str, account_name: str, issuer: str = "Vodum") -> str:
    label = f"{issuer}:{account_name or 'admin'}"
    return (
        "otpauth://totp/"
        + quote(label)
        + f"?secret={quote(_normalize_secret(secret))}&issuer={quote(issuer)}&digits=6&period=30"
    )
