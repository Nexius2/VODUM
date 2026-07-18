# Auto-split from app.py (keep URLs/endpoints intact)
import math
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from flask import render_template, request, redirect, url_for, flash, session, current_app

from logging_utils import get_logger
from werkzeug.security import generate_password_hash, check_password_hash
from app import RESET_MAGIC, RESET_FILE

from web.helpers import get_db, send_email_via_settings
from web.security import safe_redirect_target
from secret_store import decrypt_secret
from core.auth_totp import verify_totp_code
from core.i18n import get_translator
from core.auth_local_trust import (
    LOCAL_TOTP_COOKIE_NAME,
    is_local_client_ip,
    is_valid_local_totp_trust,
    set_local_totp_trust_cookie,
)

auth_logger = get_logger("auth")


def _build_login_quote_visual_safe():
    try:
        from external.dashboard_quote_easter_egg import build_login_quote_visual

        return build_login_quote_visual()
    except Exception:
        auth_logger.exception("Unable to build login easter egg visual")
        return None


AUTH_BRUTEFORCE_MAX_ATTEMPTS = max(1, int(os.environ.get("VODUM_AUTH_MAX_ATTEMPTS", "5")))
AUTH_BRUTEFORCE_WINDOW_MINUTES = max(1, int(os.environ.get("VODUM_AUTH_WINDOW_MINUTES", "15")))
AUTH_BRUTEFORCE_LOCK_MINUTES = max(1, int(os.environ.get("VODUM_AUTH_LOCK_MINUTES", "15")))
AUTH_BRUTEFORCE_ALERT_COOLDOWN_MINUTES = max(1, int(os.environ.get("VODUM_AUTH_ALERT_COOLDOWN_MINUTES", "60")))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_sql(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _sql_to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _client_ip() -> str:
    """
    request.remote_addr suffit :
    - sans trust proxy => IP directe du client
    - avec trust proxy => ProxyFix l'a déjà corrigée
    """
    return (request.remote_addr or "unknown").strip()


def _ensure_login_attempt_row(db, scope: str, scope_value: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO auth_login_attempts(scope, scope_value, failed_attempts)
        VALUES (?, ?, 0)
        """,
        (scope, scope_value),
    )


def _get_login_attempt_row(db, scope: str, scope_value: str) -> dict:
    _ensure_login_attempt_row(db, scope, scope_value)
    row = db.query_one(
        """
        SELECT scope, scope_value, failed_attempts, first_failed_at, last_failed_at, locked_until, alert_sent_at, alert_count
        FROM auth_login_attempts
        WHERE scope = ? AND scope_value = ?
        """,
        (scope, scope_value),
    )
    return dict(row) if row else {
        "scope": scope,
        "scope_value": scope_value,
        "failed_attempts": 0,
        "first_failed_at": None,
        "last_failed_at": None,
        "locked_until": None,
        "alert_sent_at": None,
        "alert_count": 0,
    }


def _remaining_lock_seconds(row: dict, now: datetime) -> int:
    locked_until = _sql_to_dt(row.get("locked_until"))
    if not locked_until or locked_until <= now:
        return 0
    return int((locked_until - now).total_seconds())


def _register_failed_login(db, scope: str, scope_value: str, now: datetime) -> dict:
    row = _get_login_attempt_row(db, scope, scope_value)

    first_failed_at = _sql_to_dt(row.get("first_failed_at"))
    window_seconds = AUTH_BRUTEFORCE_WINDOW_MINUTES * 60

    if first_failed_at is None or (now - first_failed_at).total_seconds() > window_seconds:
        failed_attempts = 1
        first_failed_at = now
    else:
        failed_attempts = int(row.get("failed_attempts") or 0) + 1

    locked_until = None
    lock_started = False
    if failed_attempts >= AUTH_BRUTEFORCE_MAX_ATTEMPTS:
        locked_until = now + timedelta(minutes=AUTH_BRUTEFORCE_LOCK_MINUTES)
        lock_started = _remaining_lock_seconds(row, now) <= 0

    db.execute(
        """
        UPDATE auth_login_attempts
        SET
            failed_attempts = ?,
            first_failed_at = ?,
            last_failed_at = ?,
            locked_until = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND scope_value = ?
        """,
        (
            failed_attempts,
            _dt_to_sql(first_failed_at),
            _dt_to_sql(now),
            _dt_to_sql(locked_until) if locked_until else None,
            scope,
            scope_value,
        ),
    )

    updated = _get_login_attempt_row(db, scope, scope_value)
    updated["lock_started"] = lock_started
    return updated


def _reset_failed_login(db, scope: str, scope_value: str) -> None:
    db.execute(
        """
        UPDATE auth_login_attempts
        SET
            failed_attempts = 0,
            first_failed_at = NULL,
            last_failed_at = NULL,
            locked_until = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND scope_value = ?
        """,
        (scope, scope_value),
    )


def _is_login_locked(db, scope: str, scope_value: str, now: datetime) -> tuple[bool, int]:
    row = _get_login_attempt_row(db, scope, scope_value)
    remaining = _remaining_lock_seconds(row, now)

    if remaining <= 0 and row.get("locked_until"):
        _reset_failed_login(db, scope, scope_value)
        return False, 0

    return remaining > 0, remaining


def _alert_cooldown_passed(row: dict, now: datetime) -> bool:
    alert_sent_at = _sql_to_dt(row.get("alert_sent_at"))
    if not alert_sent_at:
        return True
    return (now - alert_sent_at).total_seconds() >= AUTH_BRUTEFORCE_ALERT_COOLDOWN_MINUTES * 60


def _mark_bruteforce_alert_sent(db, scope: str, scope_value: str, now: datetime) -> None:
    db.execute(
        """
        UPDATE auth_login_attempts
        SET
            alert_sent_at = ?,
            alert_count = COALESCE(alert_count, 0) + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND scope_value = ?
        """,
        (_dt_to_sql(now), scope, scope_value),
    )


def _admin_alert_email(settings: dict) -> str:
    return (
        (settings.get("contact_email") or "").strip()
        or (settings.get("admin_email") or "").strip()
        or (settings.get("mail_from") or "").strip()
    )


def _send_bruteforce_alert(db, email: str, client_ip: str, reason: str, rows: list[dict], now: datetime) -> None:
    alert_rows = [row for row in rows if row.get("lock_started") and _alert_cooldown_passed(row, now)]
    if not alert_rows:
        return

    settings = db.query_one("SELECT contact_email, admin_email, mail_from FROM settings WHERE id = 1")
    settings = dict(settings) if settings else {}
    to_email = _admin_alert_email(settings)
    if not to_email:
        auth_logger.warning("AUTH brute force alert skipped: no admin/contact email configured")
        return

    locked_scopes = ", ".join(
        f"{row.get('scope')}={row.get('scope_value')}" for row in alert_rows
    )
    subject = "VODUM security alert: login brute force detected"
    body = "\n".join([
        "A login brute force pattern was detected on the VODUM admin interface.",
        "",
        f"Locked scope(s): {locked_scopes}",
        f"Submitted email: {email or '<empty>'}",
        f"Client IP: {client_ip}",
        f"Reason: {reason}",
        f"Failed attempts threshold: {AUTH_BRUTEFORCE_MAX_ATTEMPTS}",
        f"Window: {AUTH_BRUTEFORCE_WINDOW_MINUTES} minute(s)",
        f"Lock duration: {AUTH_BRUTEFORCE_LOCK_MINUTES} minute(s)",
        f"User-Agent: {request.user_agent.string}",
    ])


    try:
        sent = send_email_via_settings(to_email, subject, body)
    except Exception as exc:
        auth_logger.error("AUTH brute force alert failed: %s", exc, exc_info=True)
        return

    if not sent:
        auth_logger.warning("AUTH brute force alert could not be sent to %s", to_email)
        return

    for row in alert_rows:
        _mark_bruteforce_alert_sent(db, row["scope"], row["scope_value"], now)

    auth_logger.warning(
        "AUTH brute force alert sent to %s for %s",
        to_email,
        locked_scopes,
    )


def _login_failed(db, email: str, client_ip: str, reason: str) -> None:
    now = _utcnow()
    rows = [_register_failed_login(db, "ip", client_ip, now)]
    if email:
        rows.append(_register_failed_login(db, "email", email, now))

    _send_bruteforce_alert(db, email, client_ip, reason, rows, now)

    auth_logger.warning(
        "AUTH login failed reason=%s email=%s ip=%s ua=%s",
        reason,
        email or "<empty>",
        client_ip,
        request.user_agent.string,
    )


def _login_locked_response(email: str, client_ip: str, remaining_seconds: int):
    remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
    flash(get_translator()("auth.login_too_many_attempts").format(minutes=remaining_minutes), "error")
    auth_logger.warning(
        "AUTH login blocked email=%s ip=%s remaining_seconds=%s ua=%s",
        email or "<empty>",
        client_ip,
        remaining_seconds,
        request.user_agent.string,
    )
    return redirect(url_for("login"))


def register(app):
    @app.route("/setup-admin", methods=["GET"])
    def setup_admin():
        return redirect(url_for("setup_wizard"))

        # Legacy first-run screen retained for compatibility with old links.
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash, admin_totp_enabled, admin_totp_secret, admin_totp_local_trust_enabled, wizard_active FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        # déjà configuré => go login/home
        if (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("login"))

        return render_template(
            "auth/setup_admin.html",
            admin_email=(s.get("admin_email") or "")
        )

    @app.route("/setup-admin/save", methods=["POST"])
    def setup_admin_save():
        return redirect(url_for("setup_wizard"))

        # Legacy endpoint retained for compatibility with old forms.
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash, admin_totp_enabled FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        # déjà configuré => go login/home
        if (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("login"))

        # Récupération + normalisation (ne plante jamais)
        email_input = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "")

        # Stricte: email obligatoire.
        # Si l'utilisateur laisse vide MAIS qu'un email existe déjà en DB, on le reprend.
        email = email_input or (s.get("admin_email") or "").strip().lower()

        # Validation stricte (pas seulement "@")
        # - non vide
        # - contient exactement un "@"
        # - pas d'espaces
        # - a un domaine avec un "."
        if (
            not email
            or " " in email
            or email.count("@") != 1
            or "." not in email.split("@", 1)[1]
        ):
            flash(get_translator()("auth.admin_email_required"), "error")
            return redirect(url_for("setup_admin"))

        # Mot de passe strict
        if len(password) < 8:
            flash(get_translator()("auth.password_too_short"), "error")
            return redirect(url_for("setup_admin"))

        pwd_hash = generate_password_hash(password)

        db.execute(
            """
            UPDATE settings
            SET admin_email = ?,
                contact_email = COALESCE(NULLIF(TRIM(contact_email), ''), ?),
                admin_password_hash = ?,
                auth_enabled = 1,
                admin_totp_enabled = 0,
                admin_totp_secret = NULL
            WHERE id = 1
            """,
            (email, email, pwd_hash),
        )

        session.clear()
        session["vodum_logged_in"] = True
        session["vodum_admin_email"] = email
        session.permanent = True

        # ensuite seulement, si aucun serveur -> page serveurs
        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("servers_list"))

        return redirect(url_for("dashboard"))

    @app.route("/login", methods=["GET"])
    def login():
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash, admin_totp_enabled FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        if not (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("setup_admin"))

        reset_host_example = os.environ.get(
            "VODUM_RESET_FILE_EXAMPLE",
            "/mnt/user/appdata/VODUM/password.reset"
        )
        reset_cmd = f'echo "{RESET_MAGIC}" > {reset_host_example}'

        return render_template(
            "auth/login.html",
            reset_available=os.path.exists(RESET_FILE),
            reset_cmd=reset_cmd,
            totp_enabled=int(s.get("admin_totp_enabled") or 0) == 1,
            next_url=safe_redirect_target(request.args.get("next"), ""),
            login_quote_visual=_build_login_quote_visual_safe(),
        )

    @app.get("/login/artwork/<kind>")
    def login_quote_artwork(kind):
        if kind not in {"poster", "backdrop"}:
            from flask import abort

            abort(404)

        try:
            from flask import Response, abort, send_file
            from core.monitoring.artwork_cache import ARTWORK_CACHE_TTL_SECONDS
            from core.monitoring.artwork_proxy import ArtworkProxyError, fetch_monitoring_artwork
            from external.dashboard_quote_easter_egg import build_login_quote_artwork_request

            artwork = build_login_quote_artwork_request(kind)
            if not artwork:
                abort(404)

            db = get_db()
            srv = db.query_one(
                """
                SELECT id, LOWER(TRIM(type)) AS type, url, local_url, public_url, token, settings_json
                FROM servers
                WHERE id = ?
                  AND LOWER(TRIM(type)) IN ('plex','jellyfin')
                LIMIT 1
                """,
                (int(artwork["server_id"]),),
            )
            if not srv:
                abort(404)

            result = fetch_monitoring_artwork(dict(srv), artwork.get("query") or {})
            cache_header = f"public, max-age={ARTWORK_CACHE_TTL_SECONDS}"

            if result["kind"] == "content":
                return Response(
                    result["content"],
                    mimetype=result["content_type"],
                    headers={"Cache-Control": cache_header, "X-VODUM-Artwork-Cache": "MISS"},
                )

            response = send_file(
                result["path"],
                mimetype=result["content_type"],
                conditional=True,
                max_age=result["max_age"],
            )
            response.headers["Cache-Control"] = f"public, max-age={result['max_age']}"
            response.headers["X-VODUM-Artwork-Cache"] = "STALE" if result["is_stale"] else "HIT"
            return response
        except ArtworkProxyError as exc:
            abort(exc.status_code)
        except Exception:
            auth_logger.exception("Unable to serve login quote artwork")
            abort(404)


    @app.route("/login/submit", methods=["POST"])
    def login_submit():
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash, admin_totp_enabled, admin_totp_secret, admin_totp_local_trust_enabled, wizard_active FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        if not (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("setup_admin"))

        now = _utcnow()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        client_ip = _client_ip()

        locked_ip, remaining_ip = _is_login_locked(db, "ip", client_ip, now)
        if locked_ip:
            return _login_locked_response(email, client_ip, remaining_ip)

        if email:
            locked_email, remaining_email = _is_login_locked(db, "email", email, now)
            if locked_email:
                return _login_locked_response(email, client_ip, remaining_email)

        expected_email = (s.get("admin_email") or "").strip().lower()
        if not email or email != expected_email:
            _login_failed(db, email, client_ip, "bad_email")
            flash(get_translator()("auth.invalid_credentials"), "error")
            return redirect(url_for("login"))

        if not check_password_hash(s["admin_password_hash"], password):
            _login_failed(db, email, client_ip, "bad_password")
            flash(get_translator()("auth.invalid_credentials"), "error")
            return redirect(url_for("login"))

        remember_local_totp = False
        if int(s.get("admin_totp_enabled") or 0) == 1:
            local_trust_enabled = int(s.get("admin_totp_local_trust_enabled") or 0) == 1
            local_totp_trusted = local_trust_enabled and is_valid_local_totp_trust(
                secret_key=current_app.secret_key,
                admin_email=email,
                stored_totp_secret=s.get("admin_totp_secret"),
                client_ip=client_ip,
                token=request.cookies.get(LOCAL_TOTP_COOKIE_NAME),
            )
            if not local_totp_trusted:
                totp_secret = decrypt_secret(s.get("admin_totp_secret"))
                totp_code = request.form.get("totp_code") or ""
                if not totp_secret or not verify_totp_code(totp_secret, totp_code):
                    _login_failed(db, email, client_ip, "bad_totp")
                    flash(get_translator()("auth.invalid_totp"), "error")
                    return redirect(url_for("login"))
                remember_local_totp = local_trust_enabled and is_local_client_ip(client_ip)

        _reset_failed_login(db, "ip", client_ip)
        _reset_failed_login(db, "email", email)

        session.clear()
        session["vodum_logged_in"] = True
        session["vodum_admin_email"] = email
        session.permanent = True

        if int(s.get("wizard_active") or 0) == 1:
            auth_logger.info("AUTH login ok; resuming installation wizard for email=%s", email)
            response = redirect(url_for("setup_wizard"))
        else:
            next_url = safe_redirect_target(
                request.form.get("next") or request.args.get("next"),
                url_for("dashboard"),
            )
            auth_logger.info("AUTH login ok email=%s ip=%s ua=%s", email, client_ip, request.user_agent.string)
            response = redirect(next_url)

        if remember_local_totp:
            set_local_totp_trust_cookie(
                response,
                secret_key=current_app.secret_key,
                admin_email=email,
                stored_totp_secret=s.get("admin_totp_secret"),
                secure=request.is_secure,
            )
        return response

    @app.post("/logout")
    def logout():
        session.clear()
        auth_logger.info("AUTH logout ip=%s ua=%s", _client_ip(), request.user_agent.string)
        return redirect(url_for("login"))

    # -----------------------------
    # SETTINGS / PARAMÈTRES
    # -----------------------------
    @app.before_request
    def setup_guard_no_servers():
        """
        Mode "setup" : si aucun serveur n'est configuré, on force l'accès
        uniquement à la page serveurs pour permettre l'initialisation.
        """
        allowed_prefixes = (
            "/static",
            "/set_language",
            "/setup",
            "/health",
            "/login",
            "/logout",
            "/setup-admin",
        )

        if request.path.startswith(allowed_prefixes):
            return

        if request.path in ("/favicon.ico",):
            return

        db = get_db()

        try:
            exists = db.query_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='servers'"
            )
            if not exists:
                return redirect(url_for("setup_wizard"))
        except Exception:
            return

        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("setup_wizard"))

    @app.before_request
    def maintenance_guard():
        allowed_prefixes = (
            "/static",
            "/set_language",
            "/health",
            "/login",
            "/logout",
            "/setup-admin",
        )

        if request.path.startswith(allowed_prefixes) or request.path in ("/favicon.ico",):
            return

        try:
            db = get_db()
            row = db.query_one("SELECT maintenance_mode FROM settings WHERE id = 1")
            if row and int(row["maintenance_mode"] or 0) == 1:
                return (
                    render_template("maintenance.html", active_page="settings"),
                    503,
                )
        except Exception:
            return




