from __future__ import annotations

import time
from functools import wraps
from urllib.parse import quote


SESSION_PRINCIPAL_KEY = "vodum_principal"
PRINCIPAL_VERSION = 1


def admin_principal(email: str, *, auth_level: str = "password") -> dict:
    return {
        "version": PRINCIPAL_VERSION,
        "account_type": "admin",
        "account_id": "1",
        "role": "admin",
        "email": str(email or "").strip().lower(),
        "auth_level": str(auth_level or "unknown"),
        "authenticated_at": int(time.time()),
    }


def portal_principal(*, portal_account_id: int, vodum_user_id: int, session_id: int, session_token: str, email="") -> dict:
    return {
        "version": PRINCIPAL_VERSION,
        "account_type": "portal",
        "account_id": str(int(portal_account_id)),
        "vodum_user_id": int(vodum_user_id),
        "portal_session_id": int(session_id),
        "portal_session_token": str(session_token),
        "role": "user",
        "email": str(email or "").strip().lower(),
        "auth_level": "password",
        "authenticated_at": int(time.time()),
    }


def open_admin_session(session_store, email: str, *, auth_level: str = "password", preserve_language=True, db=None, session_ttl=None):
    language = session_store.get("lang") if preserve_language else None
    session_store.clear()
    principal = admin_principal(email, auth_level=auth_level)
    if db is not None:
        from core.admin_sessions import create_admin_session

        server_session = create_admin_session(db, ttl=session_ttl)
        principal["admin_session_id"] = server_session["session_id"]
        principal["admin_session_token"] = server_session["token"]
    session_store[SESSION_PRINCIPAL_KEY] = principal
    if language:
        session_store["lang"] = language
    session_store.permanent = True


def open_portal_session(session_store, principal: dict, *, preserve_language=True):
    language = session_store.get("lang") if preserve_language else None
    session_store.clear()
    session_store[SESSION_PRINCIPAL_KEY] = dict(principal)
    if language:
        session_store["lang"] = language
    session_store.permanent = True


def close_auth_session(session_store) -> None:
    """Remove every authenticated and pre-authentication value from a session."""
    session_store.clear()


def current_principal(session_store=None) -> dict | None:
    if session_store is None:
        from flask import session

        store = session
    else:
        store = session_store
    value = store.get(SESSION_PRINCIPAL_KEY)
    if isinstance(value, dict):
        required = {"version", "account_type", "account_id", "role", "authenticated_at"}
        if required.issubset(value) and value.get("version") == PRINCIPAL_VERSION:
            return dict(value)
    # Read-only compatibility with sessions created before this migration.
    if store.get("vodum_logged_in") is True:
        return admin_principal(store.get("vodum_admin_email") or "", auth_level="legacy")
    return None


def update_admin_principal_email(session_store, email: str) -> None:
    principal = current_principal(session_store)
    normalized = str(email or "").strip().lower()
    if principal and principal.get("role") == "admin":
        principal["email"] = normalized
        session_store[SESSION_PRINCIPAL_KEY] = principal


def principal_has_role(principal: dict | None, role: str) -> bool:
    return bool(principal and principal.get("role") == role)


def principal_owns_user(principal: dict | None, vodum_user_id: int) -> bool:
    if principal_has_role(principal, "admin"):
        return True
    if not principal_has_role(principal, "user"):
        return False
    try:
        return int(principal.get("vodum_user_id")) == int(vodum_user_id)
    except (TypeError, ValueError):
        return False


def validate_portal_principal(db, principal: dict | None, *, session_ttl=None) -> bool:
    if not principal_has_role(principal, "user") or principal.get("account_type") != "portal":
        return False
    try:
        from core.portal_sessions import validate_portal_session

        valid = validate_portal_session(
            db,
            int(principal["portal_session_id"]),
            str(principal["portal_session_token"]),
            ttl=session_ttl,
        )
        return bool(
            valid
            and int(valid["portal_account_id"]) == int(principal["account_id"])
            and int(valid["vodum_user_id"]) == int(principal["vodum_user_id"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def validate_admin_principal(db, principal: dict | None, *, session_ttl=None) -> bool:
    if not principal_has_role(principal, "admin"):
        return False
    session_id = principal.get("admin_session_id")
    token = principal.get("admin_session_token")
    if session_id is None or not token:
        # Pre-revocation cookies cannot be invalidated safely after logout.
        # Fail closed and require one fresh login after this migration.
        return False
    try:
        from core.admin_sessions import validate_admin_session

        return validate_admin_session(
            db, int(session_id), str(token), ttl=session_ttl
        )
    except (TypeError, ValueError):
        return False


def bind_request_principal() -> None:
    from flask import g, session

    principal = current_principal()
    g.auth_principal = principal
    if principal and principal.get("auth_level") == "legacy" and SESSION_PRINCIPAL_KEY not in session:
        session[SESSION_PRINCIPAL_KEY] = principal
        session.pop("vodum_logged_in", None)
        session.pop("vodum_admin_email", None)


def permission_required(permission: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from flask import abort
            from core.portal_permissions import role_allows

            principal = current_principal()
            if not principal or not role_allows(principal.get("role"), permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import abort, redirect, request, url_for

        principal = current_principal()
        if not principal:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        if not principal_has_role(principal, "admin"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def portal_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import abort, redirect, request

        principal = current_principal()
        if not principal:
            target = quote(request.full_path.rstrip("?"), safe="/")
            return redirect(f"/portal/login?next={target}")
        if principal.get("role") not in {"admin", "user"}:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def portal_user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import abort, g

        principal = current_principal()
        if not principal_has_role(principal, "user") or principal.get("vodum_user_id") is None:
            abort(403)
        g.auth_principal = principal
        return view(*args, **kwargs)

    return wrapped
