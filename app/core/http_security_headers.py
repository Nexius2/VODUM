from __future__ import annotations

from flask import request


PORTAL_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https://challenges.cloudflare.com; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' https://challenges.cloudflare.com; "
    "frame-src https://challenges.cloudflare.com; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
)

# Some legacy Admin templates still contain inline helpers. Keep those pages
# operational while constraining scripts, connections, frames and forms to the
# application and the optional Cloudflare Turnstile widget. Inline code should
# progressively be moved to static files so 'unsafe-inline' can later be removed.
ADMIN_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
    "frame-src https://challenges.cloudflare.com; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
)


def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )

    if request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if request.path.startswith("/portal") or request.path.startswith("/api/portal/"):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Content-Security-Policy", PORTAL_CSP)
    else:
        response.headers.setdefault("Content-Security-Policy", ADMIN_CSP)
    return response
