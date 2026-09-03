import re


def normalize_phone(value, *, max_digits: int = 20):
    """Return a searchable canonical phone number or None for an empty value."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"[+0-9()./\s-]+", raw):
        raise ValueError("phone_invalid")
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 6 or len(digits) > max_digits:
        raise ValueError("phone_invalid")
    return ("+" if raw.startswith("+") else "") + digits

