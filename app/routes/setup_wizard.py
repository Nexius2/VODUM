from __future__ import annotations

from datetime import UTC, datetime
import json
import time
from pathlib import Path

from core.app_paths import imports_dir as get_imports_dir
from core.auth_totp import provisioning_uri, verify_totp_code
from core.auth_totp_enrollment import (
    consume_totp_enrollment,
    get_or_begin_totp_enrollment,
)
from core.auth_principal import open_admin_session
from core.i18n import get_available_languages, resolve_active_language
from core.setup_wizard_navigation import (
    display_setup_step as _display_step,
)
from core.setup_wizard_navigation import (
    next_setup_step as _next_step,
)
from core.setup_wizard_navigation import (
    previous_setup_step as _previous_step,
)
from core.setup_wizard_navigation import (
    setup_communications_available as _communications_available,
)
from core.setup_wizard_page_data import load_setup_wizard_page_data
from core.setup_wizard_servers import (
    count_validated_setup_servers,
    create_setup_media_server,
)
from core.setup_wizard_state import (
    decode_setup_wizard_state as _state,
)
from core.setup_wizard_state import (
    load_setup_wizard_settings as _settings,
)
from core.setup_wizard_state import (
    save_setup_wizard_progress as _save,
)
from core.smtp_settings import normalize_smtp_auth_method
from core.subscription_template_policies import validate_subscription_template_policy_limits
from flask import current_app, flash, redirect, render_template, request, session, url_for
from secret_store import encrypt_secret
from tasks_engine import enable_and_run_task_by_name
from web.helpers import get_db
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

TOTAL_STEPS = 10
SUPPORTED_LANGUAGES = {"en", "fr", "es", "de", "it"}

COPY = {
    "en": {
        "title": "VODUM installation", "step": "Step", "continue": "Continue",
        "back": "Back", "skip": "Skip for later", "finish": "Start using VODUM",
        "configure": "Configure now", "new": "Create new instance", "restore": "Restore backup",
        "admin": "Administrator account", "localization": "Localization",
        "servers": "Media servers", "communications": "Communications",
        "messages": "Message templates", "subscriptions": "Subscriptions",
        "subscription_settings": "Subscription settings", "assignment": "Subscription assignment",
        "summary": "Installation complete", "required": "At least one validated Plex or Jellyfin server is required.",
        "sync": "Synchronization starts in the background and will not block installation.",
        "saved": "Progress is saved automatically after every step.",
    },
    "fr": {
        "title": "Installation de VODUM", "step": "Étape", "continue": "Continuer",
        "back": "Retour", "skip": "Configurer plus tard", "finish": "Commencer à utiliser VODUM",
        "configure": "Configurer maintenant", "new": "Créer une nouvelle instance", "restore": "Restaurer une sauvegarde",
        "admin": "Compte administrateur", "localization": "Localisation",
        "servers": "Serveurs multimédias", "communications": "Communications",
        "messages": "Modèles de messages", "subscriptions": "Abonnements",
        "subscription_settings": "Paramètres des abonnements", "assignment": "Attribution des abonnements",
        "summary": "Installation terminée", "required": "Au moins un serveur Plex ou Jellyfin validé est obligatoire.",
        "sync": "La synchronisation démarre en arrière-plan et ne bloque pas l’installation.",
        "saved": "La progression est enregistrée automatiquement après chaque étape.",
    },
    "es": {
        "title": "Instalación de VODUM", "step": "Paso", "continue": "Continuar", "back": "Atrás",
        "skip": "Configurar más tarde", "finish": "Empezar a usar VODUM", "configure": "Configurar ahora",
        "new": "Crear nueva instancia", "restore": "Restaurar copia", "admin": "Cuenta administradora",
        "localization": "Localización", "servers": "Servidores multimedia", "communications": "Comunicaciones",
        "messages": "Plantillas de mensajes", "subscriptions": "Suscripciones",
        "subscription_settings": "Ajustes de suscripción", "assignment": "Asignación de suscripciones",
        "summary": "Instalación terminada", "required": "Se requiere al menos un servidor Plex o Jellyfin validado.",
        "sync": "La sincronización continúa en segundo plano.", "saved": "El progreso se guarda automáticamente.",
    },
    "de": {
        "title": "VODUM-Installation", "step": "Schritt", "continue": "Weiter", "back": "Zurück",
        "skip": "Später konfigurieren", "finish": "VODUM verwenden", "configure": "Jetzt konfigurieren",
        "new": "Neue Instanz erstellen", "restore": "Sicherung wiederherstellen", "admin": "Administratorkonto",
        "localization": "Lokalisierung", "servers": "Medienserver", "communications": "Kommunikation",
        "messages": "Nachrichtenvorlagen", "subscriptions": "Abonnements",
        "subscription_settings": "Abonnementeinstellungen", "assignment": "Abonnements zuweisen",
        "summary": "Installation abgeschlossen", "required": "Mindestens ein validierter Plex- oder Jellyfin-Server ist erforderlich.",
        "sync": "Die Synchronisierung läuft im Hintergrund.", "saved": "Der Fortschritt wird automatisch gespeichert.",
    },
    "it": {
        "title": "Installazione VODUM", "step": "Passaggio", "continue": "Continua", "back": "Indietro",
        "skip": "Configura più tardi", "finish": "Inizia a usare VODUM", "configure": "Configura ora",
        "new": "Crea nuova istanza", "restore": "Ripristina backup", "admin": "Account amministratore",
        "localization": "Localizzazione", "servers": "Server multimediali", "communications": "Comunicazioni",
        "messages": "Modelli messaggio", "subscriptions": "Abbonamenti",
        "subscription_settings": "Impostazioni abbonamento", "assignment": "Assegnazione abbonamenti",
        "summary": "Installazione completata", "required": "È richiesto almeno un server Plex o Jellyfin convalidato.",
        "sync": "La sincronizzazione continua in background.", "saved": "I progressi vengono salvati automaticamente.",
    },
}


def _validated_server_ids(state: dict) -> set[int]:
    result = set()
    for value in state.get("validated_server_ids") or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _wizard_subscription_policies(form) -> list[dict]:
    policies = []
    selectors = {"kill_newest", "kill_oldest", "kill_transcoding_first"}
    for prefix, rule_type, default_max in (("streams", "max_streams_per_user", 2), ("ips", "max_ips_per_user", 1)):
        if form.get(f"{prefix}_enabled") != "1":
            continue
        try:
            maximum = max(1, int(form.get(f"{prefix}_max") or default_max))
        except ValueError:
            maximum = default_max
        selector = form.get(f"{prefix}_selector") or "kill_newest"
        if selector not in selectors:
            selector = "kill_newest"
        rule = {"max": maximum, "selector": selector}
        if rule_type == "max_ips_per_user":
            rule["allow_local_ip"] = form.get("ips_lan") == "1"
        policies.append({"rule_type": rule_type, "provider": None, "server_id": None,
                         "is_enabled": 1, "priority": 100, "rule": rule})
    if form.get("bitrate_enabled") == "1":
        try:
            maximum = max(1, int(form.get("bitrate_max") or 20000))
        except ValueError:
            maximum = 20000
        policies.append({"rule_type": "max_bitrate_kbps", "provider": None, "server_id": None,
                         "is_enabled": 1, "priority": 100, "rule": {"max_kbps": maximum}})
    devices = [item.strip() for item in (form.get("devices_allowed") or "").split(",") if item.strip()]
    if form.get("devices_enabled") == "1" and devices:
        policies.append({"rule_type": "device_allowlist", "provider": None, "server_id": None,
                         "is_enabled": 1, "priority": 100, "rule": {"allowed": devices}})
    return policies


def continue_setup_wizard():
    """Redirect after a wizard action without treating it as a fresh page load."""
    session["vodum_wizard_internal_redirect"] = True
    return redirect(url_for("setup_wizard"))


def register(app):
    @app.post("/setup")
    def setup_wizard():
        db = get_db()
        settings = _settings(db)
        state = _state(settings)
        session.pop("vodum_wizard_internal_redirect", None)
        step = _display_step(db, settings, state)

        if request.method == "POST":
            action = (request.form.get("action") or "continue").strip()

            if action == "back":
                _save(db, step=_previous_step(db, step, state, settings), state=state, active=1)
                return continue_setup_wizard()

            if step == 1:
                if action == "restore":
                    upload = request.files.get("backup_file")
                    suffix = Path(secure_filename(upload.filename or "")).suffix.lower() if upload else ""
                    if not upload or suffix not in {".zip", ".sqlite", ".db"}:
                        flash("Please select a valid VODUM backup.", "error")
                        return continue_setup_wizard()
                    imports_dir = get_imports_dir()
                    imports_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                    path = imports_dir / f"restore_{timestamp}{suffix}"
                    upload.save(path)
                    (imports_dir / "restore_request_path.txt").write_text(str(path), encoding="utf-8")
                    if not enable_and_run_task_by_name("restore_backup"):
                        flash("Restore could not be queued.", "error")
                        return continue_setup_wizard()
                    state["restore"] = "queued"
                    _save(db, step=10, state=state, active=0, completed=1)
                    return continue_setup_wizard()
                state["instance"] = "new"

            elif step == 2:
                auth_method = (request.form.get("admin_auth_method") or "plex").strip().lower()
                if auth_method == "plex":
                    state["administrator"] = "plex_pending"
                    _save(db, step=3, state=state, active=1)
                    from routes.plex_auth import start_wizard_plex_link
                    return start_wizard_plex_link(db)

                email = (request.form.get("email") or "").strip().lower()
                password = request.form.get("password") or ""
                confirm = request.form.get("confirm_password") or ""
                if not email or "@" not in email or len(password) < 8 or password != confirm:
                    flash("Enter a valid email and matching password of at least 8 characters.", "error")
                    return continue_setup_wizard()

                totp_enabled = request.form.get("admin_totp_enabled") == "1"
                totp_secret = None
                if totp_enabled:
                    pending_secret = consume_totp_enrollment(session, purpose="setup")
                    totp_code = request.form.get("totp_code") or ""
                    if not pending_secret or not verify_totp_code(pending_secret, totp_code):
                        flash("Invalid two-factor authentication code.", "error")
                        return continue_setup_wizard()
                    totp_secret = encrypt_secret(pending_secret)

                db.execute(
                    """
                    UPDATE settings
                    SET admin_email=?,
                        contact_email=COALESCE(NULLIF(TRIM(contact_email), ''), ?),
                        admin_password_hash=?,
                        auth_enabled=1,
                        admin_totp_enabled=?,
                        admin_totp_secret=?
                    WHERE id=1
                    """,
                    (email, email, generate_password_hash(password), 1 if totp_enabled else 0, totp_secret),
                )
                from core.admin_auth_identities import sync_local_admin_identity
                sync_local_admin_identity(db, email)
                open_admin_session(
                    session, email,
                    auth_level="password_totp" if totp_enabled else "password",
                    db=db,
                    session_ttl=current_app.permanent_session_lifetime,
                )
                session["vodum_local_reauth_at"] = int(time.time())
                state["administrator"] = "created"

            elif step == 3:
                lang = (request.form.get("language") or "en").strip()
                timezone = (request.form.get("timezone") or "Europe/Paris").strip()
                if lang not in SUPPORTED_LANGUAGES:
                    lang = "en"
                session["lang"] = lang
                db.execute("UPDATE settings SET default_language=?, timezone=? WHERE id=1", (lang, timezone))
                state["localization"] = "configured"
                try:
                    from core.admin_auth_identities import get_admin_auth_identity
                    state["plex_auth"] = (
                        "linked" if get_admin_auth_identity(db, "plex") else "skipped"
                    )
                except Exception:
                    state["plex_auth"] = "skipped"

            elif step == 4:
                if action == "add_server":
                    result = create_setup_media_server(
                        db,
                        server_type=request.form.get("server_type") or "",
                        url=(
                            request.form.get("media_server_base_address")
                            or request.form.get("server_url")
                            or request.form.get("url")
                            or ""
                        ),
                        token=(
                            request.form.get("media_server_access_token")
                            or request.form.get("server_token")
                            or request.form.get("token")
                            or ""
                        ),
                    )
                    if not result["ok"]:
                        message = (
                            "Provider, URL and token are required."
                            if result["reason"] == "setup_server_fields_required"
                            else f"Connection failed: {result.get('detail') or ''}"
                        )
                        flash(message, "error")
                        return continue_setup_wizard()
                    state["media_server"] = "configured"
                    validated_ids = _validated_server_ids(state)
                    validated_ids.add(result["server_id"])
                    state["validated_server_ids"] = sorted(validated_ids)
                    _save(db, step=4, state=state, active=1)
                    flash(
                        "Connection successful. Synchronization started in the background.",
                        "success",
                    )
                    return continue_setup_wizard()
                validated_count = count_validated_setup_servers(db, state)
                if validated_count < 1:
                    flash(COPY.get(session.get("lang"), COPY["en"])["required"], "error")
                    return continue_setup_wizard()

            elif step == 5:
                if action == "save_communications":
                    smtp_pass_raw = (request.form.get("smtp_pass") or "").strip()
                    smtp_oauth_token_raw = (request.form.get("smtp_oauth_access_token") or "").strip()
                    discord_token_raw = (request.form.get("discord_bot_token") or "").strip()
                    smtp_pass = encrypt_secret(smtp_pass_raw) if smtp_pass_raw else settings.get("smtp_pass")
                    smtp_oauth_access_token = (
                        encrypt_secret(smtp_oauth_token_raw)
                        if smtp_oauth_token_raw
                        else settings.get("smtp_oauth_access_token")
                    )
                    discord_token = encrypt_secret(discord_token_raw) if discord_token_raw else settings.get("discord_bot_token")
                    smtp_auth_method = (request.form.get("smtp_auth_method") or "password").strip().lower()
                    if smtp_auth_method not in {"password", "oauth2"}:
                        smtp_auth_method = "password"
                    smtp_auth_method = normalize_smtp_auth_method(
                        smtp_auth_method,
                        settings,
                        smtp_pass,
                        smtp_oauth_access_token,
                    )
                    mailing_enabled = 1 if request.form.get("mailing_enabled") == "1" else 0
                    discord_enabled = 1 if request.form.get("discord_enabled") == "1" else 0
                    smtp_host = (request.form.get("smtp_host") or "").strip() or None
                    mail_from = (request.form.get("mail_from") or "").strip() or None
                    smtp_secret = smtp_oauth_access_token if smtp_auth_method == "oauth2" else smtp_pass
                    if mailing_enabled and (not smtp_host or not mail_from or not smtp_secret):
                        flash("Email requires an SMTP server, sender address and authentication secret.", "error")
                        return continue_setup_wizard()
                    if discord_enabled and not discord_token:
                        flash("Discord requires a bot token.", "error")
                        return continue_setup_wizard()
                    send_mode = (request.form.get("notifications_send_mode") or "first").strip().lower()
                    if send_mode not in {"first", "all"}:
                        send_mode = "first"
                    try:
                        smtp_port = int(request.form.get("smtp_port") or 587)
                    except ValueError:
                        flash("SMTP port must be a number.", "error")
                        return continue_setup_wizard()
                    db.execute(
                        """
                        UPDATE settings SET mailing_enabled=?, mail_from=?, smtp_host=?, smtp_port=?,
                          smtp_tls=?, smtp_user=?, smtp_pass=?, smtp_auth_method=?, smtp_oauth_access_token=?,
                          discord_enabled=?, discord_bot_token=?, notifications_send_mode=?, notifications_order=?
                        WHERE id=1
                        """,
                        (
                            mailing_enabled,
                            mail_from,
                            smtp_host,
                            smtp_port,
                            1 if request.form.get("smtp_tls") == "1" else 0,
                            (request.form.get("smtp_user") or "").strip() or None,
                            smtp_pass,
                            smtp_auth_method,
                            smtp_oauth_access_token,
                            discord_enabled,
                            discord_token,
                            send_mode,
                            "email,discord",
                        ),
                    )
                    state["communications"] = "configured" if mailing_enabled or discord_enabled else "skipped"
                    flash("Communication settings saved.", "success")
                state["communications"] = "skipped" if action == "skip" else state.get("communications", "reviewed")

            elif step == 6:
                if action == "save_template":
                    template_id = (request.form.get("template_id") or "").strip()
                    subject = (request.form.get("subject") or "").strip()
                    body = (request.form.get("body") or "").strip()
                    if not template_id.isdigit() or not subject or not body:
                        flash("Subject and message are required.", "error")
                        return continue_setup_wizard()
                    db.execute(
                        "UPDATE comm_templates SET enabled=?, subject=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (1 if request.form.get("enabled") == "1" else 0, subject, body, int(template_id)),
                    )
                    state["messages"] = "configured"
                    _save(db, step=6, state=state, active=1)
                    flash("Message template saved.", "success")
                    return continue_setup_wizard()
                state["messages"] = "skipped" if action == "skip" else state.get("messages", "reviewed")

            elif step == 7:
                if action == "save_subscription":
                    template_id_raw = (request.form.get("template_id") or "").strip()
                    template_id = int(template_id_raw) if template_id_raw.isdigit() else None
                    name = (request.form.get("name") or "").strip()
                    is_lifetime = 1 if request.form.get("is_lifetime") == "1" else 0
                    try:
                        duration_days = max(1, int(request.form.get("duration_days") or 30))
                    except ValueError:
                        flash("Duration must be a number.", "error")
                        return continue_setup_wizard()
                    if not name:
                        flash("Subscription name is required.", "error")
                        return continue_setup_wizard()
                    if db.query_one("SELECT id FROM subscription_templates WHERE name=? AND (? IS NULL OR id!=?)", (name, template_id, template_id)):
                        flash("A subscription with this name already exists.", "error")
                        return continue_setup_wizard()
                    if is_lifetime:
                        duration_days = 0
                    try:
                        subscription_value = max(0, float(request.form.get("subscription_value") or 0))
                    except ValueError:
                        subscription_value = 0
                    policies = _wizard_subscription_policies(request.form)
                    existing_template = None
                    if template_id:
                        existing_template = db.query_one(
                            "SELECT id,policies_json FROM subscription_templates WHERE id=?",
                            (template_id,),
                        )
                        if not existing_template:
                            flash("Subscription not found.", "error")
                            return continue_setup_wizard()
                        try:
                            existing_policies = json.loads(existing_template["policies_json"] or "[]")
                        except (TypeError, ValueError):
                            existing_policies = []
                        simple_types = {"max_streams_per_user", "max_ips_per_user", "max_bitrate_kbps", "device_allowlist"}
                        policies = [
                            policy for policy in existing_policies
                            if isinstance(policy, dict) and policy.get("rule_type") not in simple_types
                        ] + policies
                    policy_error = validate_subscription_template_policy_limits(policies)
                    if policy_error:
                        flash(policy_error, "error")
                        return continue_setup_wizard()
                    is_default = 1 if request.form.get("is_default") == "1" else 0
                    is_enabled = 1 if request.form.get("is_enabled") == "1" else 0
                    values = (name, (request.form.get("notes") or "").strip(), duration_days,
                              subscription_value, is_default, is_enabled, is_lifetime, json.dumps(policies))
                    if template_id:
                        db.execute("UPDATE subscription_templates SET name=?,notes=?,duration_days=?,subscription_value=?,is_default=?,is_enabled=?,is_lifetime=?,policies_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (*values, template_id))
                    else:
                        db.execute("INSERT INTO subscription_templates(name,notes,duration_days,subscription_value,is_default,is_enabled,is_lifetime,policies_json) VALUES(?,?,?,?,?,?,?,?)", values)
                    if is_default:
                        saved = db.query_one("SELECT id FROM subscription_templates WHERE name=?", (name,))
                        if saved:
                            db.execute("UPDATE subscription_templates SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END", (int(saved["id"]),))
                    state["subscriptions"] = "configured"
                    _save(db, step=7, state=state, active=1)
                    flash("Subscription saved.", "success")
                    return continue_setup_wizard()
                state["subscriptions"] = "skipped" if action == "skip" else state.get("subscriptions", "reviewed")

            elif step == 8:
                try:
                    reminder = max(0, int(request.form.get("reminder_days") or 7))
                    preavis = max(0, int(request.form.get("preavis_days") or 30))
                    min_kills = max(1, int(request.form.get("min_kills") or 3))
                except ValueError:
                    flash("Invalid numeric value.", "error")
                    return continue_setup_wizard()
                db.execute(
                    """
                    UPDATE settings SET reminder_days=?, preavis_days=?, expiry_mode=?,
                      usage_risk_enabled=?, usage_risk_send_upgrade_suggestions=?,
                      usage_risk_min_kills_before_suggestion=? WHERE id=1
                    """,
                    (
                        reminder, preavis, request.form.get("expiry_mode") or "disable",
                        1 if request.form.get("usage_risk_enabled") == "1" else 0,
                        1 if request.form.get("upgrade_suggestions") == "1" else 0,
                        min_kills,
                    ),
                )
                state["subscription_settings"] = "configured"

            elif step == 9:
                if action == "assign_subscriptions":
                    template_id = (request.form.get("template_id") or "").strip()
                    user_ids = [int(value) for value in request.form.getlist("user_ids") if value.isdigit()]
                    if not template_id.isdigit() or not user_ids:
                        flash("Select a subscription and at least one user.", "error")
                        return continue_setup_wizard()
                    if not db.query_one("SELECT id FROM subscription_templates WHERE id=? AND is_enabled=1", (int(template_id),)):
                        flash("Selected subscription is not available.", "error")
                        return continue_setup_wizard()
                    from blueprints.users import _apply_subscription_template_snapshot

                    for user_id in user_ids:
                        _apply_subscription_template_snapshot(db, user_id, int(template_id))
                    state["assignment"] = "configured"
                    _save(db, step=9, state=state, active=1)
                    flash(f"Subscription assigned to {len(user_ids)} user(s).", "success")
                    return continue_setup_wizard()
                state["assignment"] = "skipped" if action == "skip" else state.get("assignment", "reviewed")

            elif step == 10:
                _save(db, step=10, state=state, active=0, completed=1)
                return redirect(url_for("dashboard"))

            settings = _settings(db)
            next_step = _next_step(db, step, state, settings)
            _save(db, step=next_step, state=state, active=1)
            return continue_setup_wizard()

        settings = _settings(db)
        state = _state(settings)
        page_data = load_setup_wizard_page_data(db, settings, state)
        try:
            from core.admin_auth_identities import get_admin_auth_identity
            from routes.plex_auth import get_or_recover_plex_discovery_token
            page_data["plex_auth_identity"] = get_admin_auth_identity(db, "plex")
            page_data["plex_suggestions"] = []
            identity = page_data["plex_auth_identity"]
            if step == 4 and identity and int(identity.get("is_active") or 0) == 1:
                from core.plex_server_discovery import PlexDiscoveryError, automatic_plex_suggestions
                account_token = get_or_recover_plex_discovery_token(db, identity)
                if account_token:
                    try:
                        suggestions, discovery_context = automatic_plex_suggestions(
                            db,
                            provider_subject=identity["provider_subject"],
                            account_token=account_token,
                            context=session.get("vodum_plex_discovery"),
                            return_to="wizard",
                        )
                        page_data["plex_suggestions"] = suggestions
                        session["vodum_plex_discovery"] = discovery_context
                    except (PlexDiscoveryError, ValueError):
                        pass
        except Exception:
            page_data["plex_auth_identity"] = None
            page_data["plex_suggestions"] = []
        communications_available = _communications_available(settings, state)
        lang = resolve_active_language(settings)
        wizard_totp_secret = (
            get_or_begin_totp_enrollment(session, purpose="setup")
            if step == 2 and state.get("administrator") != "plex"
            else ""
        )
        return render_template(
            "setup/wizard.html",
            step=step, total_steps=TOTAL_STEPS, copy=COPY.get(lang, COPY["en"]),
            state=state, settings=settings,
            languages=get_available_languages(),
            communications_available=communications_available,
            wizard_totp_secret=wizard_totp_secret,
            wizard_totp_uri=(
                provisioning_uri(
                    wizard_totp_secret,
                    settings.get("admin_email") or "admin",
                )
                if wizard_totp_secret else ""
            ),
            **page_data,
        )

    @app.get("/setup")
    def setup_wizard_page():
        return setup_wizard()

    @app.post("/setup/restart")
    def setup_wizard_restart():
        db = get_db()
        _save(db, step=1, state={}, active=1, completed=0)
        return redirect(url_for("setup_wizard"))
