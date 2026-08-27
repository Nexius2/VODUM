from __future__ import annotations


PUBLIC_PREFIXES = ("/static", "/branding/", "/set_language", "/health", "/login/artwork/")
PUBLIC_EXACT = frozenset({"/favicon.ico"})
ADMIN_AUTH_EXACT = frozenset(
    {
        "/login", "/login/submit", "/logout", "/setup-admin",
        "/setup-admin/save", "/auth/plex/login",
        "/auth/plex/login/callback", "/auth/plex/login/totp",
    }
)
SETUP_FLOW_EXACT = frozenset(
    {
        "/auth/plex/wizard-link", "/auth/plex/link/callback",
        "/auth/plex/link/confirm",
    }
)


def classify_route_path(path: str) -> str:
    """Return a fail-closed access scope for an application path."""
    normalized = str(path or "/")
    if normalized in PUBLIC_EXACT or normalized.startswith(PUBLIC_PREFIXES):
        return "public"
    if normalized in ADMIN_AUTH_EXACT:
        return "admin_auth"
    if normalized.startswith("/setup") or normalized in SETUP_FLOW_EXACT:
        return "setup"
    if normalized.startswith("/api/portal/"):
        return "portal"
    if normalized == "/portal" or normalized.startswith("/portal/"):
        if normalized in {
            "/portal/login", "/portal/login/submit",
            "/portal/activate", "/portal/activate/submit",
            "/portal/forgot", "/portal/forgot/submit",
            "/portal/reset", "/portal/reset/submit",
            "/portal/auth/plex", "/portal/auth/plex/callback",
            "/portal/auth/plex/confirm",
        }:
            return "portal_auth"
        return "portal"
    return "admin"
