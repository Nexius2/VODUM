from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from core.payments import normalize_currency
from secret_store import SecretDecryptionError, decrypt_secret, encrypt_secret


PROVIDER_FIELDS = {
    "paypal": {
        "public": ("client_id", "webhook_id"),
        "secret": ("client_secret",),
    },
    "stripe": {
        "public": ("publishable_key",),
        "secret": ("secret_key", "webhook_secret"),
    },
    "mollie": {
        "public": (),
        "secret": ("api_key",),
    },
}


@dataclass(frozen=True)
class PaymentConfigurationSave:
    errors: tuple[str, ...]
    configuration: dict | None = None


def _json_object(value: object) -> dict[str, str]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(item).strip()
        for key, item in parsed.items()
        if item is not None and str(item).strip()
    }


def _secret_object(value: object) -> tuple[dict[str, str], bool]:
    if not value:
        return {}, True
    try:
        return _json_object(decrypt_secret(value)), True
    except SecretDecryptionError:
        return {}, False


def _provider_view(row: Mapping) -> dict:
    provider = str(row["provider"])
    fields = PROVIDER_FIELDS[provider]
    public = _json_object(row["public_config_json"])
    secrets, secrets_readable = _secret_object(row["secret_config_enc"])
    missing = [
        field for field in fields["public"] if not public.get(field)
    ] + [
        field for field in fields["secret"] if not secrets.get(field)
    ]
    if not secrets_readable:
        missing = ["secret_decryption"]
    configured = not missing
    enabled = bool(row["enabled"])
    return {
        "provider": provider,
        "enabled": enabled,
        "environment": str(row["environment"] or "sandbox"),
        "public": {field: public.get(field, "") for field in fields["public"]},
        "secret_configured": {
            field: bool(secrets.get(field)) for field in fields["secret"]
        },
        "configured": configured,
        "ready": enabled and configured,
        "missing": missing,
        "last_test_status": row["last_test_status"],
        "last_test_error_code": row["last_test_error_code"],
        "last_tested_at": row["last_tested_at"],
    }


def load_payment_configuration(db) -> dict:
    settings = db.query_one(
        "SELECT payment_enabled,payment_allow_early_renewal,"
        "payment_allow_plan_changes,subscription_currency FROM settings WHERE id=1"
    )
    rows = db.query(
        "SELECT provider,enabled,environment,public_config_json,secret_config_enc,"
        "last_test_status,last_test_error_code,last_tested_at "
        "FROM payment_provider_configs ORDER BY provider"
    ) or []
    providers_by_name = {str(row["provider"]): _provider_view(row) for row in rows}
    providers = [providers_by_name[name] for name in PROVIDER_FIELDS if name in providers_by_name]
    enabled = bool(settings and settings["payment_enabled"])
    ready_providers = [item["provider"] for item in providers if item["ready"]]
    return {
        "enabled": enabled,
        "allow_early_renewal": bool(settings and settings["payment_allow_early_renewal"]),
        "allow_plan_changes": bool(settings and settings["payment_allow_plan_changes"]),
        "currency": normalize_currency(settings["subscription_currency"] if settings else "EUR"),
        "providers": providers,
        "ready_providers": ready_providers,
        "ready": enabled and bool(ready_providers),
    }


def save_payment_configuration(db, form: Mapping) -> PaymentConfigurationSave:
    errors: list[str] = []
    try:
        currency = normalize_currency(form.get("payment_currency") or "EUR")
    except ValueError:
        errors.append("payment_currency_invalid")
        currency = "EUR"

    existing_rows = db.query(
        "SELECT provider,secret_config_enc FROM payment_provider_configs"
    ) or []
    existing = {str(row["provider"]): row["secret_config_enc"] for row in existing_rows}
    normalized: list[dict] = []
    for provider, fields in PROVIDER_FIELDS.items():
        environment = str(form.get(f"{provider}_environment") or "sandbox").strip().lower()
        if environment not in {"sandbox", "live"}:
            errors.append("payment_environment_invalid")
            environment = "sandbox"
        public = {
            field: str(form.get(f"{provider}_{field}") or "").strip()
            for field in fields["public"]
        }
        secrets, readable = _secret_object(existing.get(provider))
        if not readable:
            errors.append("payment_secret_unreadable")
        for field in fields["secret"]:
            submitted = str(form.get(f"{provider}_{field}") or "").strip()
            if submitted:
                secrets[field] = submitted
        normalized.append({
            "provider": provider,
            "enabled": int(str(form.get(f"{provider}_enabled") or "").lower() in {"1", "true", "on", "yes"}),
            "environment": environment,
            "public": public,
            "secrets": secrets,
        })
    if errors:
        return PaymentConfigurationSave(tuple(dict.fromkeys(errors)))

    with db.transaction() as cursor:
        cursor.execute(
            "UPDATE settings SET payment_enabled=?,payment_allow_early_renewal=?,"
            "payment_allow_plan_changes=0,subscription_currency=? WHERE id=1",
            (
                int(str(form.get("payment_enabled") or "").lower() in {"1", "true", "on", "yes"}),
                int(str(form.get("payment_allow_early_renewal") or "").lower() in {"1", "true", "on", "yes"}),
                currency,
            ),
        )
        for item in normalized:
            cursor.execute(
                "UPDATE payment_provider_configs SET enabled=?,environment=?,"
                "public_config_json=?,secret_config_enc=?,last_test_status=NULL,"
                "last_test_error_code=NULL,last_tested_at=NULL,updated_at=CURRENT_TIMESTAMP "
                "WHERE provider=?",
                (
                    item["enabled"], item["environment"],
                    json.dumps(item["public"], separators=(",", ":"), sort_keys=True),
                    encrypt_secret(json.dumps(item["secrets"], separators=(",", ":"), sort_keys=True))
                    if item["secrets"] else None,
                    item["provider"],
                ),
            )
    return PaymentConfigurationSave((), load_payment_configuration(db))
