from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

from flask import flash, redirect, render_template, request, session, url_for
from core.admin_auth_identities import (
    AdminIdentityConflict,
    get_admin_auth_discovery_token,
    get_admin_auth_identity,
    link_admin_auth_identity,
    set_admin_auth_discovery_token,
    unlink_admin_auth_identity,
)
from core.auth_totp import verify_totp_code
from core.plex_auth_client import (
    PlexAuthorizationIncomplete,
    PlexAuthClient,
    PlexAuthError,
    PlexPinExpired,
    PlexServiceUnavailable,
)
from core.plex_auth_flow import (
    PLEX_FLOW_SESSION_KEY,
    PLEX_FLOW_MAX_AGE_SECONDS,
    PlexFlow,
    PlexFlowExpired,
    PlexFlowInvalid,
    PlexFlowMissing,
    PlexFlowRejected,
    begin_plex_flow,
    consume_plex_flow,
)
from core.plex_server_discovery import (
    PlexDiscoveryError,
    delete_discovery,
    discover_plex_resources,
    load_discovery,
    store_discovery,
)
from core.setup_wizard_servers import create_setup_media_server, record_setup_media_servers
from core.setup_wizard_state import (
    decode_setup_wizard_state,
    load_setup_wizard_settings,
    save_setup_wizard_progress,
    should_resume_setup_wizard,
)
from logging_utils import get_logger
from secret_store import decrypt_secret, encrypt_secret
from web.helpers import get_db
from utils.version import load_app_version


logger = get_logger("auth")
PENDING_IDENTITY_KEY = "vodum_plex_pending_identity"
PENDING_LOGIN_KEY = "vodum_plex_pending_login"
DISCOVERY_SESSION_KEY = "vodum_plex_discovery"
MAX_DISCOVERY_SELECTION = 10


class PlexIdentityMismatch(PlexAuthError):
    pass


def _redirect_after_wizard_link():
    session["vodum_wizard_internal_redirect"] = True
    # The explicit one-shot URL survives the external Plex round trip even when
    # a browser/proxy rotates the session cookie. The wizard removes it from the
    # address bar as soon as the expected step has rendered.
    return redirect(url_for("setup_wizard", resume="plex"))


def _redirect_after_discovery(return_to: str):
    if return_to == "wizard":
        return redirect(url_for("setup_wizard", resume="wizard"))
    return redirect(url_for("servers_list"))


def _store_wizard_plex_flow(db, flow: PlexFlow) -> None:
    settings = load_setup_wizard_settings(db)
    state = decode_setup_wizard_state(settings)
    state["plex_link_flow"] = {
        "state_hash": hashlib.sha256(flow.state.encode("utf-8")).hexdigest(),
        "pin_id": flow.pin_id,
        "started_at": flow.started_at,
    }
    save_setup_wizard_progress(db, step=3, state=state, active=1)


def _consume_wizard_plex_flow(db, returned_state: str) -> PlexFlow:
    settings = load_setup_wizard_settings(db)
    state = decode_setup_wizard_state(settings)
    stored = state.pop("plex_link_flow", None)
    # Consume first for success, invalid state and expiry alike.
    save_setup_wizard_progress(db, state=state)
    session.pop(PLEX_FLOW_SESSION_KEY, None)
    if not isinstance(stored, dict):
        raise PlexFlowMissing("Plex wizard authentication flow is missing")
    candidate_hash = hashlib.sha256(str(returned_state or "").encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(stored.get("state_hash") or ""), candidate_hash):
        raise PlexFlowInvalid("Plex wizard authentication state is invalid")
    try:
        flow = PlexFlow(
            state=str(returned_state),
            pin_id=int(stored["pin_id"]),
            purpose="wizard-link",
            started_at=int(stored["started_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PlexFlowInvalid("Plex wizard authentication flow is invalid") from exc
    age = int(time.time()) - flow.started_at
    if age < 0 or age > PLEX_FLOW_MAX_AGE_SECONDS:
        raise PlexFlowExpired("Plex wizard authentication flow has expired")
    return flow


def _wizard_flow_matches(db, returned_state: str) -> bool:
    state = decode_setup_wizard_state(load_setup_wizard_settings(db))
    stored = state.get("plex_link_flow")
    if not isinstance(stored, dict):
        return False
    candidate_hash = hashlib.sha256(str(returned_state or "").encode("utf-8")).hexdigest()
    return hmac.compare_digest(str(stored.get("state_hash") or ""), candidate_hash)


def get_or_recover_plex_discovery_token(db, identity: dict | None) -> str:
    """Return the linked account token, recovering it from a matching Plex server."""
    if not identity or int(identity.get("is_active") or 0) != 1:
        return ""
    stored = get_admin_auth_discovery_token(db, "plex")
    if stored:
        return stored
    rows = db.query(
        "SELECT token FROM servers WHERE type='plex' AND token IS NOT NULL ORDER BY id"
    ) or []
    client = _client(db)
    for row in rows:
        candidate = str(row["token"] or "").strip()
        if not candidate:
            continue
        try:
            returned = client.fetch_identity(candidate)
        except (PlexAuthError, ValueError):
            continue
        if returned.subject == identity.get("provider_subject"):
            set_admin_auth_discovery_token(db, identity["id"], candidate)
            return candidate
    return ""


def _client(db) -> PlexAuthClient:
    row = db.query_one(
        "SELECT plex_client_identifier FROM admin_accounts WHERE id = 1"
    )
    identifier = (row["plex_client_identifier"] or "").strip() if row else ""
    if not identifier:
        raise PlexAuthError("Plex authentication is not configured")
    return PlexAuthClient(
        identifier,
        version=load_app_version(fallback="dev") or "dev",
    )


def _open_admin_session(settings: dict):
    session.clear()
    session["vodum_logged_in"] = True
    session["vodum_admin_email"] = settings.get("admin_email") or ""
    session.permanent = True
    if should_resume_setup_wizard(get_db(), settings):
        return redirect(url_for("setup_wizard", resume="wizard"))
    return redirect(url_for("dashboard"))


def _pending_login_valid(pending: object) -> bool:
    if not isinstance(pending, dict):
        return False
    try:
        age = time.time() - float(pending.get("started_at") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= 5 * 60


def _finish_plex_login(db, linked: dict, settings: dict):
    db.execute(
        """
        UPDATE admin_auth_identities
        SET last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (linked["id"],),
    )
    _plex_reset(db, subject=linked["provider_subject"])
    logger.info("AUTH Plex login ok identity_id=%s ip=%s", linked["id"], request.remote_addr)
    return _open_admin_session(settings)


def _plex_error_page(message_key: str, *, return_endpoint: str, status: int = 400):
    return_url = (
        url_for("setup_wizard", resume="wizard")
        if return_endpoint == "setup_wizard"
        else url_for(return_endpoint)
    )
    return (
        render_template(
            "auth/plex_error.html",
            message_key=message_key,
            return_url=return_url,
        ),
        status,
    )


def _plex_callback_error_key(exc: Exception) -> tuple[str, int]:
    if isinstance(exc, PlexFlowExpired):
        return "plex_auth_error_session_expired", 400
    if isinstance(exc, (PlexFlowMissing, PlexFlowInvalid)):
        return "plex_auth_error_session_invalid", 400
    if isinstance(exc, PlexPinExpired):
        return "plex_auth_error_pin_expired", 400
    if isinstance(exc, PlexAuthorizationIncomplete):
        return "plex_auth_error_cancelled", 400
    if isinstance(exc, PlexIdentityMismatch):
        return "plex_auth_error_unexpected_account", 403
    if isinstance(exc, PlexServiceUnavailable):
        return "plex_auth_error_network", 502
    return "plex_auth_callback_failed", 400


def _opaque_scope(prefix: str, value: str) -> str:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _plex_rate_scopes(*, state: str = "", subject: str = "") -> list[tuple[str, str]]:
    scopes = [("ip", f"plex:{request.remote_addr or 'unknown'}")]
    if state:
        scopes.append(("email", _opaque_scope("plex-state", state)))
    if subject:
        scopes.append(("email", _opaque_scope("plex-identity", subject)))
    return scopes


def _plex_locked(db, *, state: str = "", subject: str = "") -> bool:
    from routes.auth import _is_login_locked

    now = datetime.now(timezone.utc)
    return any(
        _is_login_locked(db, scope, value, now)[0]
        for scope, value in _plex_rate_scopes(state=state, subject=subject)
    )


def _plex_attempt(db, reason: str, *, state: str = "", subject: str = "") -> bool:
    from routes.auth import _register_failed_login, _send_bruteforce_alert

    now = datetime.now(timezone.utc)
    db.execute(
        """
        DELETE FROM auth_login_attempts
        WHERE scope = 'email'
          AND scope_value LIKE 'plex-state:%'
          AND updated_at < datetime('now', '-1 day')
        """
    )
    rows = [
        _register_failed_login(db, scope, value, now)
        for scope, value in _plex_rate_scopes(state=state, subject=subject)
    ]
    _send_bruteforce_alert(db, "", request.remote_addr or "unknown", reason, rows, now)
    return any(row.get("locked_until") for row in rows)


def _plex_reset(db, *, state: str = "", subject: str = "") -> None:
    from routes.auth import _reset_failed_login

    for scope, value in _plex_rate_scopes(state=state, subject=subject):
        if value.startswith("plex-state:"):
            db.execute(
                "DELETE FROM auth_login_attempts WHERE scope = ? AND scope_value = ?",
                (scope, value),
            )
        else:
            _reset_failed_login(db, scope, value)


def _add_discovered_server(db, candidate: dict, preferred_url: str = "") -> tuple[str, int | None]:
    machine_id = str(candidate.get("machine_identifier") or "").strip()
    if not machine_id or db.query_one(
        "SELECT id FROM servers WHERE type='plex' AND server_identifier=?",
        (machine_id,),
    ):
        return "skipped", None
    token = str(candidate.get("access_token") or "").strip()
    urls = [str(item.get("uri") or "").strip() for item in candidate.get("connections") or []]
    urls = [url for url in urls if url]
    if preferred_url in urls:
        urls = [preferred_url, *[url for url in urls if url != preferred_url]]
    for url in urls[:2]:
        result = create_setup_media_server(
            db,
            server_type="plex",
            url=url,
            token=token,
            expected_identifier=machine_id,
        )
        if result.get("ok"):
            return "added", int(result["server_id"])
        if result.get("reason") == "setup_server_duplicate":
            return "skipped", None
    return "failed", None


def start_wizard_plex_link(db):
    existing_identity = get_admin_auth_identity(db, "plex")
    if existing_identity and int(existing_identity.get("is_active") or 0) == 1:
        return _redirect_after_wizard_link()
    if _plex_locked(db) or _plex_attempt(db, "plex_wizard_link_start"):
        flash("plex_auth_rate_limited", "error")
        return _redirect_after_wizard_link()
    try:
        client = _client(db)
        pin = client.create_pin()
        flow = begin_plex_flow(session, pin_id=pin.id, purpose="wizard-link")
        _store_wizard_plex_flow(db, flow)
        callback = url_for(
            "plex_auth_link_callback", state=flow.state, _external=True
        )
        logger.info("AUTH Plex wizard link started ip=%s", request.remote_addr)
        return redirect(client.build_authorization_url(pin, callback))
    except (PlexAuthError, ValueError):
        flash("plex_auth_start_failed", "error")
        return _redirect_after_wizard_link()


def register(app):
    @app.post("/auth/plex/discovery/start")
    def plex_discovery_start():
        if session.get("vodum_logged_in") is not True:
            return redirect(url_for("login"))
        db = get_db()
        linked = get_admin_auth_identity(db, "plex")
        if not linked or int(linked.get("is_active") or 0) != 1:
            flash("plex_discovery_link_required", "error")
            return redirect(url_for("servers_list"))
        now = time.time()
        try:
            last_started = float(session.get("vodum_plex_discovery_started_at") or 0)
        except (TypeError, ValueError):
            last_started = 0
        if now - last_started < 30:
            flash("plex_discovery_rate_limited", "error")
            return redirect(url_for("servers_list"))
        return_to = "wizard" if request.form.get("return_to") == "wizard" else "servers"
        try:
            previous = session.pop(DISCOVERY_SESSION_KEY, None) or {}
            if previous.get("id"):
                delete_discovery(db, str(previous["id"]))
            client = _client(db)
            pin = client.create_pin()
            flow = begin_plex_flow(session, pin_id=pin.id, purpose="discover")
            session["vodum_plex_discovery_started_at"] = now
            session["vodum_plex_discovery_return_to"] = return_to
            callback = url_for(
                "plex_discovery_callback", state=flow.state, _external=True
            )
            return redirect(client.build_authorization_url(pin, callback))
        except (PlexAuthError, ValueError):
            flash("plex_discovery_failed", "error")
            return _redirect_after_discovery(return_to)

    @app.get("/auth/plex/discovery/callback")
    def plex_discovery_callback():
        if session.get("vodum_logged_in") is not True:
            return redirect(url_for("login"))
        db = get_db()
        state = request.args.get("state") or ""
        return_to = session.get("vodum_plex_discovery_return_to") or "servers"
        try:
            flow = consume_plex_flow(
                session,
                returned_state=state,
                expected_purpose="discover",
            )
            client = _client(db)
            account_token = client.wait_for_token(flow.pin_id)
            if not account_token:
                raise PlexAuthorizationIncomplete("Plex authorization was not completed")
            returned = client.fetch_identity(account_token)
            linked = get_admin_auth_identity(db, "plex")
            if (
                not linked
                or int(linked.get("is_active") or 0) != 1
                or linked.get("provider_subject") != returned.subject
            ):
                raise PlexIdentityMismatch("Plex identity does not match the linked account")
            set_admin_auth_discovery_token(db, linked["id"], account_token)
            existing_rows = db.query(
                "SELECT server_identifier FROM servers WHERE type='plex'"
            ) or []
            existing_ids = [row["server_identifier"] for row in existing_rows]
            candidates = discover_plex_resources(
                account_token, existing_identifiers=existing_ids
            )
            nonce = secrets.token_urlsafe(24)
            discovery_id = store_discovery(
                db,
                session_secret=nonce,
                provider_subject=returned.subject,
                candidates=candidates,
            )
            session[DISCOVERY_SESSION_KEY] = {
                "id": discovery_id,
                "nonce": nonce,
                "return_to": return_to,
                "expires_at": int(time.time()) + 10 * 60,
            }
            logger.info(
                "AUTH Plex discovery completed identity_id=%s resources=%s",
                linked.get("id"),
                len(candidates),
            )
            return redirect(url_for("plex_discovery_results"))
        except (PlexFlowRejected, PlexAuthError, PlexDiscoveryError, ValueError):
            logger.warning("AUTH Plex discovery failed ip=%s", request.remote_addr)
            flash("plex_discovery_failed", "error")
            return _redirect_after_discovery(return_to)

    @app.get("/auth/plex/discovery/results")
    def plex_discovery_results():
        if session.get("vodum_logged_in") is not True:
            return redirect(url_for("login"))
        context = session.get(DISCOVERY_SESSION_KEY) or {}
        db = get_db()
        if not context.get("id") or int(context.get("expires_at") or 0) < int(time.time()):
            if context.get("id"):
                delete_discovery(db, str(context["id"]))
            session.pop(DISCOVERY_SESSION_KEY, None)
            flash("plex_discovery_expired", "error")
            return _redirect_after_discovery(context.get("return_to") or "servers")
        candidates = load_discovery(
            db,
            discovery_id=str(context.get("id") or ""),
            session_secret=str(context.get("nonce") or ""),
        )
        safe_candidates = []
        existing_rows = db.query(
            "SELECT server_identifier FROM servers WHERE type='plex'"
        ) or []
        existing_ids = {row["server_identifier"] for row in existing_rows}
        for item in candidates:
            safe = dict(item)
            safe.pop("access_token", None)
            safe["already_added"] = safe["machine_identifier"] in existing_ids
            safe["selectable"] = bool(item.get("access_token") and safe["connections"]) and not safe["already_added"]
            safe["primary_url"] = (
                safe["connections"][0]["uri"] if safe["connections"] else ""
            )
            safe_candidates.append(safe)
        return render_template(
            "servers/plex_discovery.html",
            candidates=safe_candidates,
            return_to=context.get("return_to") or "servers",
            wizard_resume_url=url_for("setup_wizard", resume="wizard"),
            active_page="servers",
        )

    @app.post("/auth/plex/discovery/add")
    def plex_discovery_add():
        if session.get("vodum_logged_in") is not True:
            return redirect(url_for("login"))
        context = session.get(DISCOVERY_SESSION_KEY) or {}
        db = get_db()
        if not context.get("id") or int(context.get("expires_at") or 0) < int(time.time()):
            if context.get("id"):
                delete_discovery(db, str(context["id"]))
            session.pop(DISCOVERY_SESSION_KEY, None)
            flash("plex_discovery_expired", "error")
            return _redirect_after_discovery(context.get("return_to") or "servers")
        candidates = load_discovery(
            db,
            discovery_id=str(context.get("id") or ""),
            session_secret=str(context.get("nonce") or ""),
        )
        selected = set(request.form.getlist("candidate_id")[:MAX_DISCOVERY_SELECTION])
        linked = get_admin_auth_identity(db, "plex")
        added = skipped = failed = 0
        added_ids = []
        for candidate in candidates:
            if candidate["id"] not in selected:
                continue
            if (
                not linked
                or int(linked.get("is_active") or 0) != 1
                or linked.get("provider_subject") != candidate.get("provider_subject")
            ):
                failed += 1
                continue
            preferred_url = str(request.form.get(f"preferred_url_{candidate['id']}") or "").strip()
            try:
                outcome, server_id = _add_discovered_server(db, candidate, preferred_url)
            except Exception:
                logger.warning("AUTH Plex discovery server add failed")
                outcome, server_id = "failed", None
            if outcome == "added":
                added += 1
                added_ids.append(server_id)
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
        delete_discovery(db, str(context.get("id") or ""))
        session.pop(DISCOVERY_SESSION_KEY, None)
        if context.get("return_to") == "wizard":
            record_setup_media_servers(db, added_ids)
        flash(
            "plex_discovery_add_summary",
            "success" if added and not failed else "warning",
        )
        logger.info(
            "AUTH Plex discovery add summary identity_id=%s added=%s skipped=%s failed=%s",
            linked.get("id") if linked else None,
            added,
            skipped,
            failed,
        )
        return _redirect_after_discovery(context.get("return_to") or "servers")

    @app.post("/auth/plex/wizard-link")
    def plex_auth_wizard_link_start():
        db = get_db()
        wizard_settings = load_setup_wizard_settings(db)
        wizard_state = decode_setup_wizard_state(wizard_settings)
        wizard_authorized = (
            int(wizard_settings.get("wizard_active") or 0) == 1
            and wizard_state.get("administrator") == "plex_pending"
        )
        if session.get("vodum_logged_in") is not True and not wizard_authorized:
            return redirect(url_for("login"))
        return start_wizard_plex_link(db)

    @app.post("/auth/plex/login")
    def plex_auth_login_start():
        db = get_db()
        if _plex_locked(db):
            logger.warning("AUTH Plex login start rate-limited ip=%s", request.remote_addr)
            flash("plex_auth_rate_limited", "error")
            return redirect(url_for("login"))
        if _plex_attempt(db, "plex_login_start"):
            logger.warning("AUTH Plex login start threshold reached ip=%s", request.remote_addr)
            flash("plex_auth_rate_limited", "error")
            return redirect(url_for("login"))
        identity = get_admin_auth_identity(db, "plex")
        if not identity or int(identity.get("is_active") or 0) != 1:
            flash("plex_auth_login_unavailable", "error")
            return redirect(url_for("login"))
        try:
            client = _client(db)
            pin = client.create_pin()
            flow = begin_plex_flow(session, pin_id=pin.id, purpose="login")
            callback = url_for(
                "plex_auth_login_callback", state=flow.state, _external=True
            )
            logger.info("AUTH Plex login started ip=%s", request.remote_addr)
            return redirect(client.build_authorization_url(pin, callback))
        except (PlexAuthError, ValueError):
            logger.warning("AUTH Plex login start failed ip=%s", request.remote_addr)
            flash("plex_auth_start_failed", "error")
            return redirect(url_for("login"))

    @app.get("/auth/plex/login/callback")
    def plex_auth_login_callback():
        returned_state = request.args.get("state") or ""
        db = get_db()
        if _plex_locked(db, state=returned_state):
            logger.warning("AUTH Plex login callback rate-limited ip=%s", request.remote_addr)
            flash("plex_auth_rate_limited", "error")
            return redirect(url_for("login"))
        try:
            flow = consume_plex_flow(
                session,
                returned_state=returned_state,
                expected_purpose="login",
            )
            client = _client(db)
            token = client.wait_for_token(flow.pin_id)
            if not token:
                raise PlexAuthorizationIncomplete("Plex authorization was not completed")
            returned = client.fetch_identity(token)
            linked = get_admin_auth_identity(db, "plex")
            if (
                not linked
                or int(linked.get("is_active") or 0) != 1
                or linked.get("provider_subject") != returned.subject
            ):
                raise PlexIdentityMismatch("Plex identity does not match the linked account")
            settings = db.query_one(
                """
                SELECT admin_email, wizard_active, admin_totp_enabled,
                       admin_totp_secret
                FROM settings WHERE id = 1
                """
            )
            settings = dict(settings) if settings else {}
            config = db.query_one(
                "SELECT plex_require_vodum_totp FROM admin_accounts WHERE id = 1"
            )
            require_vodum_totp = (
                int(settings.get("admin_totp_enabled") or 0) == 1
                and config
                and int(config["plex_require_vodum_totp"] or 0) == 1
            )
            if require_vodum_totp:
                session[PENDING_LOGIN_KEY] = {
                    "identity_id": linked["id"],
                    "subject": linked["provider_subject"],
                    "started_at": time.time(),
                }
                return render_template("auth/plex_totp.html")
            return _finish_plex_login(db, linked, settings)
        except (PlexFlowRejected, PlexAuthError, ValueError) as exc:
            _plex_attempt(db, "plex_login_callback", state=returned_state)
            logger.warning("AUTH Plex login callback rejected ip=%s", request.remote_addr)
            key, status = _plex_callback_error_key(exc)
            return _plex_error_page(key, return_endpoint="login", status=status)

    @app.post("/auth/plex/login/totp")
    def plex_auth_login_totp():
        pending = session.pop(PENDING_LOGIN_KEY, None)
        if not _pending_login_valid(pending):
            flash("plex_auth_login_failed", "error")
            return redirect(url_for("login"))

        db = get_db()
        linked = get_admin_auth_identity(db, "plex")
        settings_row = db.query_one(
            """
            SELECT admin_email, wizard_active, admin_totp_enabled,
                   admin_totp_secret
            FROM settings WHERE id = 1
            """
        )
        settings = dict(settings_row) if settings_row else {}
        secret = decrypt_secret(settings.get("admin_totp_secret"))
        if (
            not linked
            or linked["id"] != pending.get("identity_id")
            or linked["provider_subject"] != pending.get("subject")
            or int(linked.get("is_active") or 0) != 1
            or int(settings.get("admin_totp_enabled") or 0) != 1
            or not secret
            or not verify_totp_code(secret, request.form.get("totp_code") or "")
        ):
            _plex_attempt(db, "plex_totp", subject=str(pending.get("subject") or ""))
            logger.warning("AUTH Plex VODUM TOTP rejected ip=%s", request.remote_addr)
            flash("plex_auth_totp_failed", "error")
            return redirect(url_for("login"))
        logger.info("AUTH Plex VODUM TOTP verified identity_id=%s", linked["id"])
        return _finish_plex_login(db, linked, settings)

    @app.post("/auth/plex/link")
    def plex_auth_link_start():
        if session.get("vodum_logged_in") is not True:
            return redirect(url_for("login"))
        db = get_db()
        if _plex_locked(db):
            flash("plex_auth_rate_limited", "error")
            return redirect(url_for("settings_page"))
        if _plex_attempt(db, "plex_link_start"):
            flash("plex_auth_rate_limited", "error")
            return redirect(url_for("settings_page"))
        requested_action = (request.form.get("action") or "link").strip().lower()
        purpose = "replace" if requested_action == "replace" else "link"
        existing = get_admin_auth_identity(db, "plex")
        if existing and purpose != "replace":
            flash("plex_auth_identity_conflict", "error")
            return redirect(url_for("settings_page"))
        if not existing and purpose == "replace":
            purpose = "link"

        try:
            client = _client(db)
            pin = client.create_pin()
            flow = begin_plex_flow(session, pin_id=pin.id, purpose=purpose)
            callback = url_for(
                "plex_auth_link_callback", state=flow.state, _external=True
            )
            logger.info("AUTH Plex link started ip=%s", request.remote_addr)
            return redirect(client.build_authorization_url(pin, callback))
        except (PlexAuthError, ValueError):
            logger.warning("AUTH Plex link start failed ip=%s", request.remote_addr)
            flash("plex_auth_start_failed", "error")
            return redirect(url_for("settings_page"))

    @app.get("/auth/plex/link/callback")
    def plex_auth_link_callback():
        returned_state = request.args.get("state") or ""
        db = get_db()
        stored_flow = session.get(PLEX_FLOW_SESSION_KEY)
        wizard_return = (
            isinstance(stored_flow, dict)
            and stored_flow.get("purpose") == "wizard-link"
        ) or _wizard_flow_matches(db, returned_state)
        wizard_settings = load_setup_wizard_settings(db)
        wizard_authorized = wizard_return and int(wizard_settings.get("wizard_active") or 0) == 1
        if session.get("vodum_logged_in") is not True and not wizard_authorized:
            return redirect(url_for("login"))
        if _plex_locked(db, state=returned_state):
            flash("plex_auth_rate_limited", "error")
            if wizard_return:
                return _redirect_after_wizard_link()
            return redirect(url_for("settings_page"))
        try:
            flow = (
                _consume_wizard_plex_flow(db, returned_state)
                if wizard_return
                else consume_plex_flow(session, returned_state=returned_state)
            )
            if flow.purpose not in {"link", "replace", "wizard-link"}:
                raise PlexFlowRejected("Plex authentication purpose does not match")
            client = _client(db)
            token = client.wait_for_token(flow.pin_id)
            if not token:
                raise PlexAuthorizationIncomplete("Plex authorization was not completed")
            identity = client.fetch_identity(token)
            session[PENDING_IDENTITY_KEY] = {
                "subject": identity.subject,
                "username": identity.username,
                "email": identity.email,
                "display_name": identity.display_name,
                "allow_replace": flow.purpose == "replace",
                "return_to_wizard": flow.purpose == "wizard-link",
                "discovery_token_enc": encrypt_secret(token),
            }
            _plex_reset(db, state=returned_state)
            return render_template(
                "auth/plex_link_confirm.html",
                identity=identity,
                return_to_wizard=flow.purpose == "wizard-link",
            )
        except (PlexFlowRejected, PlexAuthError, ValueError) as exc:
            _plex_attempt(db, "plex_link_callback", state=returned_state)
            session.pop(PENDING_IDENTITY_KEY, None)
            logger.warning("AUTH Plex link callback rejected ip=%s", request.remote_addr)
            key, status = _plex_callback_error_key(exc)
            return _plex_error_page(
                key,
                return_endpoint="setup_wizard" if wizard_return else "settings_page",
                status=status,
            )

    @app.post("/auth/plex/link/confirm")
    def plex_auth_link_confirm():
        pending = session.get(PENDING_IDENTITY_KEY)
        if not isinstance(pending, dict) or not pending.get("subject"):
            flash("plex_auth_confirmation_expired", "error")
            return redirect(url_for("settings_page"))
        return_to_wizard = pending.get("return_to_wizard") is True
        wizard_settings = load_setup_wizard_settings(get_db())
        wizard_authorized = return_to_wizard and int(wizard_settings.get("wizard_active") or 0) == 1
        if session.get("vodum_logged_in") is not True and not wizard_authorized:
            return redirect(url_for("login"))
        session.pop(PENDING_IDENTITY_KEY, None)
        try:
            identity = link_admin_auth_identity(
                get_db(),
                provider="plex",
                subject=pending["subject"],
                display_name=pending.get("display_name") or pending.get("username") or "",
                display_email=pending.get("email") or "",
                allow_replace=pending.get("allow_replace") is True,
            )
            pending_token = decrypt_secret(pending.get("discovery_token_enc"))
            set_admin_auth_discovery_token(get_db(), identity["id"], pending_token)
        except (AdminIdentityConflict, ValueError):
            logger.warning("AUTH Plex link conflict ip=%s", request.remote_addr)
            flash("plex_auth_identity_conflict", "error")
            if return_to_wizard:
                return _redirect_after_wizard_link()
            return redirect(url_for("settings_page"))
        logger.info("AUTH Plex identity linked identity_id=%s", identity["id"])
        if return_to_wizard:
            db = get_db()
            admin_email = (pending.get("email") or "").strip()
            db.execute(
                """
                UPDATE settings
                SET admin_email=?,
                    contact_email=COALESCE(NULLIF(TRIM(contact_email), ''), NULLIF(?, '')),
                    admin_password_hash=NULL,
                    auth_enabled=1,
                    admin_totp_enabled=0,
                    admin_totp_secret=NULL
                WHERE id=1
                """,
                (admin_email, admin_email),
            )
            db.execute(
                "DELETE FROM admin_auth_identities WHERE admin_account_id=1 AND provider='local'"
            )
            state = decode_setup_wizard_state(load_setup_wizard_settings(db))
            state["administrator"] = "plex"
            state["plex_auth"] = "linked"
            save_setup_wizard_progress(db, step=3, state=state, active=1)
            active_lang = session.get("lang")
            session.clear()
            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = admin_email
            if active_lang:
                session["lang"] = active_lang
            session.permanent = True
        flash("plex_auth_linked", "success")
        if return_to_wizard:
            return _redirect_after_wizard_link()
        return redirect(url_for("settings_page"))

    @app.post("/auth/plex/unlink")
    def plex_auth_unlink():
        if session.get("vodum_logged_in") is not True:
            return redirect(url_for("login"))
        db = get_db()
        removed = unlink_admin_auth_identity(db, provider="plex")
        session.pop(PENDING_IDENTITY_KEY, None)
        logger.info("AUTH Plex identity unlinked removed=%s", int(removed))
        flash("plex_auth_unlinked" if removed else "plex_auth_not_linked", "success")
        return redirect(url_for("settings_page"))
