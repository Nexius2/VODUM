from flask import request
from flask.sessions import SecureCookieSessionInterface


class VodumSessionInterface(SecureCookieSessionInterface):
    """
    Keep HTTPS cookies strict while still allowing direct HTTP access on a LAN.

    A Secure cookie is intentionally not sent over http://192.168.x.x. If the
    app has Secure/SameSite=None enabled for the public HTTPS URL, a direct local
    HTTP login loses the session cookie between GET /login and POST /login/submit,
    which makes the CSRF guard reject the request with 403 before auth/2FA runs.
    """

    def get_cookie_secure(self, app):
        # Every cookie created through an HTTPS request must be Secure.  The
        # request scheme is trustworthy only after ConditionalProxyFix has
        # validated the reverse proxy, so an untrusted X-Forwarded-Proto header
        # cannot enable these semantics.  Direct LAN HTTP remains supported.
        return bool(request.is_secure)

    def get_cookie_samesite(self, app):
        value = super().get_cookie_samesite(app)
        # Plex authentication leaves VODUM for app.plex.tv, then returns through
        # a top-level GET callback. A Strict cookie is not sent on that
        # cross-site return, so the PIN/state stored in the session is lost.
        # Emit the flow-start response as Lax without weakening other sessions.
        if request.endpoint in {"portal_plex_start", "portal_plex_link_start"}:
            return "Lax"
        if value == "None" and not request.is_secure:
            return "Lax"
        return value
