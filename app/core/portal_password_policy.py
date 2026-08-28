from __future__ import annotations


def password_policy(settings: dict | None) -> dict:
    values = dict(settings) if settings is not None else {}
    return {
        "min_length": max(8, min(128, int(values.get("portal_password_min_length") or 8))),
        "upper": int(values.get("portal_password_require_upper") or 0) == 1,
        "lower": int(values.get("portal_password_require_lower") or 0) == 1,
        "digit": int(values.get("portal_password_require_digit") or 0) == 1,
        "symbol": int(values.get("portal_password_require_symbol") or 0) == 1,
    }


def password_policy_error(password: str, settings: dict | None) -> str | None:
    value = str(password or "")
    policy = password_policy(settings)
    if len(value) < policy["min_length"]:
        return "portal_password_too_short"
    if policy["upper"] and not any(char.isupper() for char in value):
        return "portal_password_policy_failed"
    if policy["lower"] and not any(char.islower() for char in value):
        return "portal_password_policy_failed"
    if policy["digit"] and not any(char.isdigit() for char in value):
        return "portal_password_policy_failed"
    if policy["symbol"] and not any(not char.isalnum() for char in value):
        return "portal_password_policy_failed"
    return None
