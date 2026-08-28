import secrets
import time
from flask import current_app, flash, redirect, render_template, request, session, url_for

from core.auth_principal import SESSION_PRINCIPAL_KEY, open_portal_session
from core.portal_local_auth import (
    activate_local_invitation,
    authenticate_local_user,
    invitation_is_valid,
    consume_password_reset,
    create_password_reset,
    password_reset_is_valid,
    revoke_password_reset,
)
from core.portal_bruteforce import (
    clear_login_failures,
    login_locked,
    register_login_failure,
)
from core.portal_audit import record_portal_event
from core.portal_sessions import create_portal_session, revoke_portal_session
from core.auth_principal import portal_principal
from core.portal_account_state import state_allows_portal
from core.portal_plex_identity import PlexPortalLinkAmbiguous, resolve_plex_portal_account
from core.portal_jellyfin_auth import (
    JellyfinPortalAuthError, authenticate_jellyfin_user, resolve_jellyfin_portal_account,
)
from core.plex_auth_client import PlexAuthClient, PlexAuthError
from core.plex_auth_flow import begin_plex_flow, consume_plex_flow, PlexFlowRejected
from core.portal_email import portal_email_payload
from core.turnstile import turnstile_config, verify_turnstile
from core.portal_rate_limit import portal_request_allowed
from core.portal_readiness import local_portal_test_request_allowed
from core.portal_auth_methods import link_identity
from web.helpers import get_db
from web.security import get_client_ip, safe_redirect_target


def _build_portal_login_visual():
    try:
        from external.dashboard_quote_easter_egg import build_login_quote_visual
        return build_login_quote_visual()
    except Exception:
        current_app.logger.exception("Unable to build portal login easter egg visual")
        return None


def _portal_settings(db):
    row = db.query_one(
        "SELECT portal_enabled,portal_local_test_enabled,portal_public_url,portal_local_auth_enabled,portal_plex_auth_enabled,portal_jellyfin_auth_enabled,turnstile_enabled,turnstile_site_key,"
        "turnstile_secret_key,turnstile_mode,turnstile_protect_portal FROM settings WHERE id=1"
    )
    return dict(row) if row else {}


def _turnstile_guard(db):
    settings = _portal_settings(db)
    result = verify_turnstile(
        settings, request.form.get("cf-turnstile-response") or "",
        remote_ip=get_client_ip(), hostname=request.host,
    )
    return result


def _audit_turnstile_failure(db, result):
    if result.get("ok"):
        return
    record_portal_event(
        db, "turnstile_failed", "blocked", client_ip=get_client_ip(),
        user_agent=request.user_agent.string, details={"reason": result.get("reason")},
    )


def register(app):
    def _portal_available(settings):
        return int(settings.get("portal_enabled") or 0) == 1 or local_portal_test_request_allowed(settings, request.remote_addr or "", request.host)
    def _plex_client(db):
        row = db.query_one("SELECT plex_client_identifier FROM admin_accounts WHERE id=1")
        identifier = str(row["plex_client_identifier"] or "").strip() if row else ""
        return PlexAuthClient(identifier, version=str(current_app.config.get("APP_VERSION") or "unknown"))

    def _open_plex_portal_session(db, linked):
        row = db.query_one(
            "SELECT pa.id,pa.status,pa.vodum_user_id,vu.status AS user_status,vu.email "
            "FROM portal_accounts pa JOIN vodum_users vu ON vu.id=pa.vodum_user_id WHERE pa.id=?",
            (int(linked["portal_account_id"]),),
        )
        if not row or not state_allows_portal(row["status"], row["user_status"]):
            return False
        created = create_portal_session(db, int(row["id"]))
        open_portal_session(session, portal_principal(
            portal_account_id=int(row["id"]), vodum_user_id=int(row["vodum_user_id"]),
            session_id=created["session_id"], session_token=created["token"],
            email=row["email"] or "",
        ))
        return True

    def _jellyfin_servers(db):
        return [dict(row) for row in (db.query(
            "SELECT id,name FROM servers WHERE LOWER(type)='jellyfin' ORDER BY name,id"
        ) or [])]

    @app.post("/portal/auth/jellyfin")
    def portal_jellyfin_login():
        db = get_db(); settings = _portal_settings(db)
        if not _portal_available(settings) or int(settings.get("portal_jellyfin_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not portal_request_allowed(db, "jellyfin_login", get_client_ip(), limit=30):
            return render_template("portal/auth_message.html", message_key="portal_login_locked"), 429
        try:
            identity = authenticate_jellyfin_user(
                db, int(request.form.get("server_id") or 0),
                request.form.get("username") or "", request.form.get("password") or "",
            )
            linked = resolve_jellyfin_portal_account(db, identity)
            if not linked or not _open_plex_portal_session(db, linked):
                raise JellyfinPortalAuthError("portal_invalid_credentials")
            record_portal_event(db, "jellyfin_login_success", "success", portal_account_id=int(linked["portal_account_id"]), client_ip=get_client_ip(), user_agent=request.user_agent.string)
            return redirect(url_for("portal_home"))
        except (JellyfinPortalAuthError, ValueError):
            record_portal_event(db, "jellyfin_login_failed", "failure", client_ip=get_client_ip(), user_agent=request.user_agent.string)
            flash("portal_invalid_credentials", "error")
            return redirect(url_for("portal_login"))

    @app.post("/portal/auth/plex")
    def portal_plex_start():
        db = get_db(); settings = _portal_settings(db)
        if not _portal_available(settings) or int(settings.get("portal_plex_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not portal_request_allowed(db, "plex_start", get_client_ip(), limit=30):
            return render_template("portal/auth_message.html", message_key="portal_login_locked"), 429
        try:
            client = _plex_client(db); pin = client.create_pin()
            flow = begin_plex_flow(session, pin_id=pin.id, purpose="login")
            callback = f"{str(settings.get('portal_public_url') or '').rstrip('/')}/portal/auth/plex/callback?state={flow.state}"
            return redirect(client.build_authorization_url(pin, callback))
        except (ValueError, PlexAuthError):
            return render_template("portal/auth_message.html", message_key="portal_plex_unavailable"), 503

    @app.post("/portal/profile/methods/plex")
    def portal_plex_link_start():
        principal = session.get(SESSION_PRINCIPAL_KEY) or {}
        if principal.get("role") != "user": return redirect(url_for("portal_login"))
        try:
            client = _plex_client(get_db()); pin = client.create_pin(); flow = begin_plex_flow(session, pin_id=pin.id, purpose="link")
            settings = _portal_settings(get_db()); callback = f"{str(settings.get('portal_public_url') or '').rstrip('/')}/portal/auth/plex/callback?state={flow.state}"
            return redirect(client.build_authorization_url(pin, callback))
        except (ValueError, PlexAuthError):
            flash("portal_plex_unavailable", "error"); return redirect(url_for("portal_profile"))

    @app.get("/portal/auth/plex/callback")
    def portal_plex_callback():
        db = get_db()
        try:
            flow = consume_plex_flow(session, returned_state=request.args.get("state") or "")
            client = _plex_client(db); token = client.wait_for_token(flow.pin_id)
            if not token: raise PlexAuthError("authorization incomplete")
            identity = client.fetch_identity(token)
            if flow.purpose == "link":
                principal = session.get(SESSION_PRINCIPAL_KEY) or {}
                if principal.get("role") != "user": raise ValueError("unavailable")
                link_identity(db, int(principal["account_id"]), "plex", identity.subject)
                session["portal_reauthenticated_at"] = int(time.time())
                flash("portal_method_linked", "success")
                return redirect(url_for("portal_profile"))
            if flow.purpose != "login": raise ValueError("unavailable")
            try:
                linked = resolve_plex_portal_account(db, identity.subject, provider_email=identity.email)
            except PlexPortalLinkAmbiguous as ambiguous:
                nonce = secrets.token_urlsafe(24)
                session["portal_plex_pending"] = {"nonce": nonce, "subject": identity.subject, "candidates": list(ambiguous.candidate_user_ids), "expires": int(time.time()) + 300}
                return render_template("portal/plex_confirm.html", nonce=nonce, candidates=ambiguous.candidate_user_ids)
            if not linked or not _open_plex_portal_session(db, linked):
                raise ValueError("unavailable")
            return redirect(url_for("portal_home"))
        except (PlexFlowRejected, PlexAuthError, ValueError) as exc:
            current_app.logger.warning("Portal Plex callback failed (%s): %s", type(exc).__name__, exc)
            return render_template("portal/auth_message.html", message_key="portal_plex_login_failed", login_quote_visual=_build_portal_login_visual()), 400

    @app.post("/portal/auth/plex/confirm")
    def portal_plex_confirm():
        pending = session.pop("portal_plex_pending", None)
        try:
            if not isinstance(pending, dict) or int(pending.get("expires") or 0) < int(time.time()) or not secrets.compare_digest(str(pending.get("nonce") or ""), str(request.form.get("nonce") or "")):
                raise ValueError("expired")
            candidates = [int(value) for value in pending.get("candidates") or []]
            candidate_index = int(request.form.get("candidate") or -1)
            if candidate_index < 0 or candidate_index >= len(candidates):
                raise ValueError("invalid candidate")
            selected = candidates[candidate_index]
            linked = resolve_plex_portal_account(get_db(), pending["subject"], confirmed_vodum_user_id=selected)
            if not linked or not _open_plex_portal_session(get_db(), linked): raise ValueError("unavailable")
            return redirect(url_for("portal_home"))
        except (ValueError, KeyError):
            return render_template("portal/auth_message.html", message_key="portal_plex_login_failed"), 400

    @app.get("/portal/activate")
    def portal_activate():
        token = (request.args.get("token") or "").strip()
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not invitation_is_valid(get_db(), token):
            return render_template("portal/auth_message.html", message_key="portal_invitation_invalid"), 400
        return render_template("portal/activate.html", token=token)

    @app.post("/portal/activate/submit")
    def portal_activate_submit():
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not portal_request_allowed(get_db(), "activate", get_client_ip()):
            return render_template("portal/auth_message.html", message_key="portal_login_locked"), 429
        token = (request.form.get("token") or "").strip()
        password = request.form.get("password") or ""
        if password != (request.form.get("password_confirm") or ""):
            flash("portal_password_mismatch", "error")
            return redirect(url_for("portal_activate", token=token))
        try:
            account_id = activate_local_invitation(get_db(), token, password)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("portal_activate", token=token))
        record_portal_event(get_db(), "account_activated", "success", portal_account_id=account_id)
        flash("portal_account_activated", "success")
        return redirect(url_for("portal_login"))

    @app.get("/portal/login")
    def portal_login():
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or not (int(settings.get("portal_local_auth_enabled") or 0) == 1 or int(settings.get("portal_plex_auth_enabled") or 0) == 1 or int(settings.get("portal_jellyfin_auth_enabled") or 0) == 1):
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        return render_template("portal/login.html", next_url=request.args.get("next") or "", turnstile=turnstile_config(settings), portal_local_auth_enabled=int(settings.get("portal_local_auth_enabled") or 0)==1, portal_plex_auth_enabled=int(settings.get("portal_plex_auth_enabled") or 0)==1, portal_jellyfin_auth_enabled=int(settings.get("portal_jellyfin_auth_enabled") or 0)==1, jellyfin_servers=_jellyfin_servers(get_db()), login_quote_visual=_build_portal_login_visual())

    @app.post("/portal/login/submit")
    def portal_login_submit():
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        db = get_db()
        if not portal_request_allowed(db, "login", get_client_ip(), limit=60):
            flash("portal_login_locked", "error")
            return redirect(url_for("portal_login"))
        challenge = _turnstile_guard(db)
        if not challenge["ok"]:
            _audit_turnstile_failure(db, challenge)
            flash("turnstile_verification_failed", "error")
            return redirect(url_for("portal_login"))
        email = request.form.get("email") or ""
        client_ip = get_client_ip()
        if login_locked(db, "ip", client_ip) or login_locked(db, "email", email):
            record_portal_event(db, "login_locked", "blocked", client_ip=client_ip, user_agent=request.user_agent.string)
            flash("portal_login_locked", "error")
            return redirect(url_for("portal_login"))
        principal = authenticate_local_user(db, email, request.form.get("password") or "")
        if not principal:
            register_login_failure(db, "ip", client_ip)
            register_login_failure(db, "email", email)
            record_portal_event(db, "login_failed", "failure", client_ip=client_ip, user_agent=request.user_agent.string)
            flash("portal_invalid_credentials", "error")
            return redirect(url_for("portal_login"))
        clear_login_failures(db, "ip", client_ip)
        clear_login_failures(db, "email", email)
        record_portal_event(
            db, "login_success", "success", portal_account_id=int(principal["account_id"]),
            client_ip=client_ip, user_agent=request.user_agent.string,
        )
        payload = portal_email_payload(db, int(principal["vodum_user_id"]), "new_login")
        if payload:
            from web.helpers import send_email_via_settings
            send_email_via_settings(payload["to"], payload["subject"], payload["body"])
        open_portal_session(session, principal)
        return redirect(safe_redirect_target(request.form.get("next"), "/portal"))

    @app.get("/portal/forgot")
    def portal_forgot():
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        return render_template("portal/forgot.html", turnstile=turnstile_config(settings))

    @app.post("/portal/forgot/submit")
    def portal_forgot_submit():
        db = get_db()
        settings = _portal_settings(db)
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not portal_request_allowed(db, "forgot", get_client_ip()):
            flash("portal_login_locked", "error")
            return redirect(url_for("portal_forgot"))
        challenge = _turnstile_guard(db)
        if not challenge["ok"]:
            _audit_turnstile_failure(db, challenge)
            flash("turnstile_verification_failed", "error")
            return redirect(url_for("portal_forgot"))
        settings = db.query_one(
            "SELECT portal_public_url,portal_local_auth_enabled FROM settings WHERE id=1"
        )
        if settings and int(settings["portal_local_auth_enabled"] or 0) == 1:
            reset = create_password_reset(db, request.form.get("email") or "")
            public_url = (settings["portal_public_url"] or "").strip().rstrip("/")
            if reset and public_url:
                from web.helpers import send_email_via_settings

                reset_url = f"{public_url}/portal/reset?token={reset['token']}"
                payload = portal_email_payload(db, int(reset["vodum_user_id"]), "password_reset", {"url": reset_url}) if reset.get("vodum_user_id") else None
                if not payload or not send_email_via_settings(payload["to"], payload["subject"], payload["body"]):
                    revoke_password_reset(db, reset["token"])
            if reset:
                record_portal_event(
                    db, "password_reset_requested", "success",
                    portal_account_id=reset["portal_account_id"],
                    client_ip=get_client_ip(), user_agent=request.user_agent.string,
                )
        flash("portal_reset_requested", "success")
        return redirect(url_for("portal_login"))

    @app.get("/portal/reset")
    def portal_reset():
        token = (request.args.get("token") or "").strip()
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not password_reset_is_valid(get_db(), token):
            return render_template("portal/auth_message.html", message_key="portal_reset_invalid"), 400
        return render_template("portal/reset.html", token=token)

    @app.post("/portal/reset/submit")
    def portal_reset_submit():
        settings = _portal_settings(get_db())
        if not _portal_available(settings) or int(settings.get("portal_local_auth_enabled") or 0) != 1:
            return render_template("portal/auth_message.html", message_key="portal_unavailable"), 503
        if not portal_request_allowed(get_db(), "reset", get_client_ip()):
            return render_template("portal/auth_message.html", message_key="portal_login_locked"), 429
        token = (request.form.get("token") or "").strip()
        password = request.form.get("password") or ""
        if password != (request.form.get("password_confirm") or ""):
            flash("portal_password_mismatch", "error")
            return redirect(url_for("portal_reset", token=token))
        try:
            account_id = consume_password_reset(get_db(), token, password)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("portal_reset", token=token))
        record_portal_event(get_db(), "password_reset_completed", "success", portal_account_id=account_id)
        flash("portal_password_reset_done", "success")
        return redirect(url_for("portal_login"))

    @app.post("/portal/logout")
    def portal_logout():
        principal = session.get(SESSION_PRINCIPAL_KEY) or {}
        if principal.get("role") == "user" and principal.get("portal_session_id"):
            revoke_portal_session(get_db(), int(principal["portal_session_id"]), reason="logout")
            record_portal_event(
                get_db(), "logout", "success", portal_account_id=int(principal["account_id"]),
                client_ip=get_client_ip(), user_agent=request.user_agent.string,
            )
        session.clear()
        return redirect(url_for("portal_login"))
