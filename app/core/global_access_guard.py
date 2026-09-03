from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from flask import abort, current_app, flash, redirect, request, session, url_for

from core.auth_principal import (
    SESSION_PRINCIPAL_KEY,
    close_auth_session,
    current_principal,
    principal_has_role,
    validate_admin_principal,
    validate_portal_principal,
)
from core.portal_account_state import effective_portal_account_state, state_message
from core.route_access_policy import classify_route_path
from logging_utils import get_logger
from web.helpers import get_db
from web.security import get_client_ip


security_logger = get_logger("security")
DEFAULT_ALLOWED_NETS = "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def _request_hostname(host_value: object) -> str:
    try:
        parsed = urlsplit(f"//{str(host_value or '').strip()}")
        _ = parsed.port  # Force malformed/non-numeric ports to raise.
        return (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _configured_admin_hostname() -> str:
    """Return the optional public Admin host used for strict host isolation."""
    raw_value = (
        os.environ.get("VODUM_ADMIN_PUBLIC_URL")
        or os.environ.get("VODUM_ADMIN_PUBLIC_HOST")
        or ""
    ).strip()
    if not raw_value:
        return ""
    if "://" not in raw_value:
        raw_value = f"//{raw_value}"
    try:
        return (urlsplit(raw_value).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _get_auth_settings() -> dict:
    row = get_db().query_one(
        """
        SELECT s.admin_email, s.admin_password_hash, s.auth_enabled,
               s.portal_public_url,
               EXISTS(
                   SELECT 1 FROM admin_auth_identities i
                   WHERE i.admin_account_id=1
                     AND i.provider='plex'
                     AND i.is_active=1
               ) AS plex_auth_configured
        FROM settings s WHERE s.id = 1
        """
    )
    return dict(row) if row else {
        "admin_email": "", "admin_password_hash": None,
        "auth_enabled": 1, "plex_auth_configured": 0,
    }


def _is_auth_configured(settings: dict) -> bool:
    return bool(
        (settings.get("admin_password_hash") or "").strip()
        or int(settings.get("plex_auth_configured") or 0) == 1
    )


def _ip_allowed(remote_ip: str) -> bool:
    if (os.environ.get("VODUM_IP_FILTER") or "1").strip() in (
        "0", "false", "False", "no", "NO",
    ):
        return True
    allowed = (os.environ.get("VODUM_ALLOWED_NETS") or DEFAULT_ALLOWED_NETS).strip()
    try:
        ip = ipaddress.ip_address(remote_ip)
    except ValueError:
        return False
    for part in allowed.split(","):
        try:
            if part.strip() and ip in ipaddress.ip_network(part.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def register_global_access_guard(app) -> None:
    """Register fail-closed IP, portal-host and role checks for every route."""

    @app.before_request
    def global_access_guard():
        client_ip = get_client_ip()
        if not _ip_allowed(client_ip):
            security_logger.warning("Blocked request | ip=%s | path=%s", client_ip, request.path)
            abort(403)

        settings = _get_auth_settings()
        access_scope = classify_route_path(request.path)
        expected_portal_host = str(
            urlsplit(str(settings.get("portal_public_url") or "")).hostname or ""
        ).lower().rstrip(".")
        expected_admin_host = _configured_admin_hostname()
        request_host = _request_hostname(request.host)

        # Isolate the virtual hosts only when a distinct Admin host is explicitly
        # configured. With one shared host, /login and /portal/login must coexist
        # and the existing path, role and server-side session checks provide the
        # separation. Public assets remain available on either host.
        if (
            expected_portal_host
            and expected_admin_host
            and expected_portal_host != expected_admin_host
            and request_host == expected_portal_host
            and access_scope in {"admin", "admin_auth", "setup"}
        ):
            abort(404)

        if access_scope in {"portal", "portal_auth"}:
            if expected_portal_host and request_host != expected_portal_host:
                abort(404)

        if access_scope == "public":
            return None

        auth_enabled = settings.get("auth_enabled")
        if int(1 if auth_enabled is None else auth_enabled) == 0:
            return None

        configured = _is_auth_configured(settings)
        if access_scope in {"portal", "portal_auth"}:
            if access_scope == "portal_auth":
                return None
            principal = current_principal()
            if not principal:
                return redirect(f"/portal/login?next={request.path}")
            if principal.get("role") not in {"admin", "user"}:
                abort(403)
            if principal.get("role") == "admin" and not validate_admin_principal(
                get_db(), principal,
                session_ttl=current_app.permanent_session_lifetime,
            ):
                close_auth_session(session)
                return redirect(url_for("login", next=request.path))
            if principal.get("role") == "user" and not validate_portal_principal(
                get_db(), principal,
                session_ttl=current_app.permanent_session_lifetime,
            ):
                account = get_db().query_one(
                    "SELECT pa.status,vu.status AS user_status FROM portal_accounts pa "
                    "JOIN vodum_users vu ON vu.id=pa.vodum_user_id WHERE pa.id=?",
                    (int(principal.get("account_id") or 0),),
                )
                if account:
                    flash(
                        state_message(effective_portal_account_state(account["status"], account["user_status"])),
                        "error",
                    )
                session.pop(SESSION_PRINCIPAL_KEY, None)
                return redirect(f"/portal/login?next={request.path}")
            return None

        if access_scope == "setup":
            if not configured:
                return None
            principal = current_principal()
            if principal_has_role(principal, "admin") and validate_admin_principal(
                get_db(), principal,
                session_ttl=current_app.permanent_session_lifetime,
            ):
                return None
            if principal:
                close_auth_session(session)
            return redirect(url_for("login", next=request.path))

        if access_scope == "admin_auth":
            if request.path in ("/login", "/login/submit") and not configured:
                return redirect(url_for("setup_admin"))
            return None

        if not configured:
            return redirect(url_for("setup_admin"))

        principal = current_principal()
        if not principal:
            return redirect(url_for("login", next=request.path))
        if not principal_has_role(principal, "admin"):
            abort(403)
        if not validate_admin_principal(
            get_db(), principal,
            session_ttl=current_app.permanent_session_lifetime,
        ):
            close_auth_session(session)
            return redirect(url_for("login", next=request.path))
        return None
