from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


SUPPORTED_PAYMENT_PROVIDERS = frozenset({"paypal", "stripe", "mollie"})
SUPPORTED_PAYMENT_STATUSES = frozenset(
    {"pending", "processing", "paid", "failed", "cancelled", "refunded"}
)

_ALLOWED_TRANSITIONS = {
    "pending": frozenset({"processing", "paid", "failed", "cancelled"}),
    "processing": frozenset({"paid", "failed", "cancelled"}),
    "paid": frozenset({"refunded"}),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "refunded": frozenset(),
}


def normalize_currency(value: object) -> str:
    currency = str(value or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("payment_currency_invalid")
    return currency


def amount_to_minor(value: object, *, exponent: int = 2) -> int:
    if exponent < 0 or exponent > 3:
        raise ValueError("payment_currency_exponent_invalid")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("payment_amount_invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("payment_amount_invalid")
    factor = Decimal(10) ** exponent
    scaled = amount * factor
    rounded = scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if scaled != rounded:
        raise ValueError("payment_amount_precision_invalid")
    return int(rounded)


def calculate_renewed_expiration(
    current_expiration: str | None,
    *,
    paid_on: date,
    duration_days: int,
) -> str:
    if duration_days <= 0:
        raise ValueError("payment_plan_duration_invalid")
    try:
        current = date.fromisoformat(str(current_expiration or ""))
    except ValueError:
        current = None
    base = current if current is not None and current >= paid_on else paid_on
    return (base + timedelta(days=int(duration_days))).isoformat()


def payment_status_transition_allowed(current: str, target: str) -> bool:
    if current not in SUPPORTED_PAYMENT_STATUSES or target not in SUPPORTED_PAYMENT_STATUSES:
        return False
    return target == current or target in _ALLOWED_TRANSITIONS[current]
