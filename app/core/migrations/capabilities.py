"""Explicit provider contract for migration planning and execution."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class MigrationProviderCapabilities:
    provider: str
    account_mode: str
    requires_email: bool
    supports_library_access: bool
    supports_source_access_removal: bool
    supports_access_rollback: bool
    access_worker_task: str
    empty_access_action: str


_CAPABILITIES = {
    "plex": MigrationProviderCapabilities(
        provider="plex",
        account_mode="invite",
        requires_email=True,
        supports_library_access=True,
        supports_source_access_removal=True,
        supports_access_rollback=True,
        access_worker_task="apply_plex_access_updates",
        empty_access_action="revoke",
    ),
    "jellyfin": MigrationProviderCapabilities(
        provider="jellyfin",
        account_mode="create_local",
        requires_email=False,
        supports_library_access=True,
        supports_source_access_removal=True,
        supports_access_rollback=True,
        access_worker_task="apply_jellyfin_access_updates",
        empty_access_action="sync",
    ),
}

MIGRATION_PROVIDER_CAPABILITIES = MappingProxyType(_CAPABILITIES)
SUPPORTED_MIGRATION_PROVIDERS = frozenset(_CAPABILITIES)


def get_migration_provider_capabilities(provider: str) -> MigrationProviderCapabilities:
    normalized = str(provider or "").strip().lower()
    try:
        return MIGRATION_PROVIDER_CAPABILITIES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported migration provider: {normalized or 'unknown'}") from exc


def migration_access_action(provider: str, *, has_remaining_access: bool) -> str:
    capabilities = get_migration_provider_capabilities(provider)
    return "sync" if has_remaining_access else capabilities.empty_access_action
