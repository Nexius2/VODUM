from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class PaymentOrderRequest:
    public_id: str
    description: str
    amount_minor: int
    currency: str
    return_url: str
    cancel_url: str


@dataclass(frozen=True)
class ProviderCheckout:
    provider_order_id: str
    approval_url: str | None = None
    client_payload: Mapping[str, str] | None = None


@dataclass(frozen=True)
class VerifiedPaymentEvent:
    provider: str
    event_id: str
    event_type: str
    provider_order_id: str | None
    provider_transaction_id: str | None
    status: str
    amount_minor: int | None
    currency: str | None
    provider_created_at: str | None = None


class PaymentProvider(Protocol):
    name: str

    def validate_configuration(self) -> tuple[bool, str | None]: ...

    def create_checkout(self, order: PaymentOrderRequest) -> ProviderCheckout: ...

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> VerifiedPaymentEvent: ...

    def retrieve_payment(self, provider_order_id: str) -> VerifiedPaymentEvent: ...
