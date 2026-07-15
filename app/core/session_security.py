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
        configured_secure = bool(app.config.get("SESSION_COOKIE_SECURE", False))
        return configured_secure and request.is_secure

    def get_cookie_samesite(self, app):
        value = super().get_cookie_samesite(app)
        if value == "None" and not request.is_secure:
            return "Lax"
        return value