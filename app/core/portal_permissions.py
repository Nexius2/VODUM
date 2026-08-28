from __future__ import annotations


ADMIN = "admin"
USER = "user"

# Server-side permission contract. Routes will consume this map as the portal
# is implemented; templates must never be treated as an authorization layer.
ROLE_PERMISSIONS = {
    ADMIN: frozenset({"*"}),
    USER: frozenset(
        {
            "portal.home.read_own",
            "portal.profile.read_own",
            "portal.profile.update_own",
            "portal.subscription.read_own",
            "portal.media_access.read_own",
            "portal.media_access.update_own",
            "portal.monitoring.read_own",
            "portal.support.read",
            "portal.api.read_own",
        }
    ),
}


def role_allows(role: str, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(str(role or "").strip().lower(), frozenset())
    return "*" in permissions or permission in permissions
