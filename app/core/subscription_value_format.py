from __future__ import annotations

from decimal import Decimal, InvalidOperation


def format_subscription_value(value):
    """Remove a meaningless decimal suffix without altering custom labels."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        text = str(value).strip()
        try:
            number = Decimal(text)
        except InvalidOperation:
            return value
    if number == number.to_integral_value():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")
