"""Read-only /api/v1 endpoints and the admin pages that manage API tokens."""

from __future__ import annotations

from functools import wraps

from flask import current_app, flash, g, jsonify, make_response, redirect, request, url_for

from core import public_api
from core.auth_principal import admin_required
from core.error_reporting import log_handled_failure
from core.i18n import get_translator
from logging_utils import get_logger
from web.helpers import add_log, get_db
from web.security import get_client_ip

security_logger = get_logger("security")


def _json(payload, status=200, headers=None):
    response = make_response(jsonify(payload), status)
    response.headers["Cache-Control"] = "no-store"
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def _reject(reason, status, headers=None):
    security_logger.warning(
        "Rejected API request | reason=%s | ip=%s | path=%s", reason, get_client_ip(), request.path,
    )
    return _json({"error": reason}, status, headers)


def api_token_required(scope=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            db = get_db()
            token = public_api.find_active_token(db, public_api.extract_request_token(request.headers))
            if not token:
                return _reject("unauthorized", 401, {"WWW-Authenticate": 'Bearer realm="vodum"'})
            if scope and scope not in token["scopes"]:
                return _reject("insufficient_scope", 403)
            retry_after = public_api.rate_limiter.check(token["id"])
            if retry_after:
                return _reject("rate_limited", 429, {"Retry-After": str(retry_after)})
            try:
                public_api.record_token_use(db, token["id"])
            except Exception:
                # Usage counters must never make a dashboard read fail.
                log_handled_failure("public_api.record_use", token_id=token["id"])
            return view(*args, **kwargs)

        return wrapped

    return decorator


def register(app):
    @app.get("/api/v1/status")
    @api_token_required()
    def public_api_status():
        return _json({"app": "VODUM", "version": g.get("app_version", "dev"), "api_version": 1})

    @app.get("/api/v1/stats")
    @api_token_required("stats")
    def public_api_stats():
        return _json(public_api.load_stats(get_db()))

    @app.get("/api/v1/servers")
    @api_token_required("servers")
    def public_api_servers():
        return _json({"servers": public_api.load_servers(get_db())})

    @app.get("/api/v1/sessions")
    @api_token_required("sessions")
    def public_api_sessions():
        sessions = public_api.load_sessions(get_db())
        return _json({"count": len(sessions), "sessions": sessions})

    @app.get("/api/v1/users/summary")
    @api_token_required("users")
    def public_api_users_summary():
        return _json(public_api.load_users_summary(get_db()))

    @app.post("/settings/api-tokens/create")
    @admin_required
    def api_token_create():
        t = get_translator()
        scopes = public_api.normalize_scopes(request.form.getlist("scopes"))
        try:
            token_id, token = public_api.create_token(get_db(), request.form.get("name"), scopes)
        except public_api.ApiTokenError as exc:
            flash(t(str(exc)), "error")
            return redirect(url_for("settings_page") + "#api-access")
        name = " ".join(str(request.form.get("name") or "").split())[: public_api.NAME_MAX_LENGTH]
        add_log("info", "api", "API token created", {"token_id": token_id, "name": name, "scopes": scopes})
        # The settings page is rendered directly with the token in a modal, once.
        # The token is never stored in the session or in a flash message.
        g.api_token_created = {"token": token, "name": name, "scopes": scopes}
        response = make_response(current_app.view_functions["settings_page"]())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/settings/api-tokens/<int:token_id>/revoke")
    @admin_required
    def api_token_revoke(token_id):
        t = get_translator()
        if public_api.revoke_token(get_db(), token_id):
            add_log("info", "api", "API token revoked", {"token_id": token_id})
            flash(t("api_token_revoked"), "success")
        return redirect(url_for("settings_page") + "#api-access")
