from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.app_paths import imports_dir as get_imports_dir
from core.auth_totp import verify_totp_code
from core.i18n import get_available_languages
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
from flask import flash, redirect, render_template, request, session, url_for
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


def register(app):
    @app.post("/setup")
    def setup_wizard():
        db = get_db()
        settings = _settings(db)
        state = _state(settings)
        step = _display_step(db, settings, state)

        if request.method == "POST":
            action = (request.form.get("action") or "continue").strip()

            if action == "back":
                _save(db, step=_previous_step(db, step, state, settings), state=state, active=1)
                return redirect(url_for("setup_wizard"))

            if step == 1:
                if action == "restore":
                    upload = request.files.get("backup_file")
                    suffix = Path(secure_filename(upload.filename or "")).suffix.lower() if upload else ""
                    if not upload or suffix not in {".zip", ".sqlite", ".db"}:
                        flash("Please select a valid VODUM backup.", "error")
                        return redirect(url_for("setup_wizard"))
                    imports_dir = get_imports_dir()
                    imports_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                    path = imports_dir / f"restore_{timestamp}{suffix}"
                    upload.save(path)
                    (imports_dir / "restore_request_path.txt").write_text(str(path), encoding="utf-8")
                    if not enable_and_run_task_by_name("restore_backup"):
                        flash("Restore could not be queued.", "error")
                        return redirect(url_for("setup_wizard"))
                    state["restore"] = "queued"
                    _save(db, step=10, state=state, active=0, completed=1)
                    return redirect(url_for("setup_wizard"))
                state["instance"] = "new"

            elif step == 2:
                email = (request.form.get("email") or "").strip().lower()
                password = request.form.get("password") or ""
                confirm = request.form.get("confirm_password") or ""
                if not email or "@" not in email or len(password) < 8 or password != confirm:
                    flash("Enter a valid email and matching password of at least 8 characters.", "error")
                    return redirect(url_for("setup_wizard"))

                totp_enabled = request.form.get("admin_totp_enabled") == "1"
                totp_secret = None
                if totp_enabled:
                    pending_secret = (request.form.get("pending_totp_secret") or "").strip()
                    totp_code = request.form.get("totp_code") or ""
                    if not pending_secret or not verify_totp_code(pending_secret, totp_code):
                        flash("Invalid two-factor authentication code.", "error")
                        return redirect(url_for("setup_wizard"))
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
                session.clear()
                session["vodum_logged_in"] = True
                session["vodum_admin_email"] = email
                session.permanent = True
                state["administrator"] = "created"

            elif step == 3:
                lang = (request.form.get("language") or "en").strip()
                timezone = (request.form.get("timezone") or "Europe/Paris").strip()
                if lang not in SUPPORTED_LANGUAGES:
                    lang = "en"
                session["lang"] = lang
                db.execute("UPDATE settings SET default_language=?, timezone=? WHERE id=1", (lang, timezone))
                state["localization"] = "configured"

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
                        return redirect(url_for("setup_wizard"))
                    state["media_server"] = "configured"
                    validated_ids = _validated_server_ids(state)
                    validated_ids.add(result["server_id"])
                    state["validated_server_ids"] = sorted(validated_ids)
                    _save(db, step=4, state=state, active=1)
                    flash(
                        "Connection successful. Synchronization started in the background.",
                        "success",
                    )
                    return redirect(url_for("setup_wizard"))
                validated_count = count_validated_setup_servers(db, state)
                if validated_count < 1:
                    flash(COPY.get(session.get("lang"), COPY["en"])["required"], "error")
                    return redirect(url_for("setup_wizard"))

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
                        return redirect(url_for("setup_wizard"))
                    if discord_enabled and not discord_token:
                        flash("Discord requires a bot token.", "error")
                        return redirect(url_for("setup_wizard"))
                    send_mode = (request.form.get("notifications_send_mode") or "first").strip().lower()
                    if send_mode not in {"first", "all"}:
                        send_mode = "first"
                    try:
                        smtp_port = int(request.form.get("smtp_port") or 587)
                    except ValueError:
                        flash("SMTP port must be a number.", "error")
                        return redirect(url_for("setup_wizard"))
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
                    _save(db, step=5, state=state, active=1)
                    flash("Communication settings saved.", "success")
                    return redirect(url_for("setup_wizard"))
                state["communications"] = "skipped" if action == "skip" else state.get("communications", "reviewed")

            elif step == 6:
                if action == "save_template":
                    template_id = (request.form.get("template_id") or "").strip()
                    subject = (request.form.get("subject") or "").strip()
                    body = (request.form.get("body") or "").strip()
                    if not template_id.isdigit() or not subject or not body:
                        flash("Subject and message are required.", "error")
                        return redirect(url_for("setup_wizard"))
                    db.execute(
                        "UPDATE comm_templates SET enabled=?, subject=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (1 if request.form.get("enabled") == "1" else 0, subject, body, int(template_id)),
                    )
                    state["messages"] = "configured"
                    _save(db, step=6, state=state, active=1)
                    flash("Message template saved.", "success")
                    return redirect(url_for("setup_wizard"))
                state["messages"] = "skipped" if action == "skip" else state.get("messages", "reviewed")

            elif step == 7:
                if action == "add_subscription":
                    name = (request.form.get("name") or "").strip()
                    is_lifetime = 1 if request.form.get("is_lifetime") == "1" else 0
                    try:
                        duration_days = max(1, int(request.form.get("duration_days") or 30))
                    except ValueError:
                        flash("Duration must be a number.", "error")
                        return redirect(url_for("setup_wizard"))
                    if not name:
                        flash("Subscription name is required.", "error")
                        return redirect(url_for("setup_wizard"))
                    if db.query_one("SELECT id FROM subscription_templates WHERE name=?", (name,)):
                        flash("A subscription with this name already exists.", "error")
                        return redirect(url_for("setup_wizard"))
                    db.execute(
                        """
                        INSERT INTO subscription_templates(name,notes,duration_days,subscription_value,is_default,is_enabled,is_lifetime,policies_json)
                        VALUES(?,?,?,?,0,1,?,'[]')
                        """,
                        (name, (request.form.get("notes") or "").strip(), duration_days, 0, is_lifetime),
                    )
                    state["subscriptions"] = "configured"
                    _save(db, step=7, state=state, active=1)
                    flash("Subscription created.", "success")
                    return redirect(url_for("setup_wizard"))
                state["subscriptions"] = "skipped" if action == "skip" else state.get("subscriptions", "reviewed")

            elif step == 8:
                try:
                    reminder = max(0, int(request.form.get("reminder_days") or 7))
                    preavis = max(0, int(request.form.get("preavis_days") or 30))
                    min_kills = max(1, int(request.form.get("min_kills") or 3))
                except ValueError:
                    flash("Invalid numeric value.", "error")
                    return redirect(url_for("setup_wizard"))
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
                        return redirect(url_for("setup_wizard"))
                    if not db.query_one("SELECT id FROM subscription_templates WHERE id=? AND is_enabled=1", (int(template_id),)):
                        flash("Selected subscription is not available.", "error")
                        return redirect(url_for("setup_wizard"))
                    from blueprints.users import _apply_subscription_template_snapshot

                    for user_id in user_ids:
                        _apply_subscription_template_snapshot(db, user_id, int(template_id))
                    state["assignment"] = "configured"
                    _save(db, step=9, state=state, active=1)
                    flash(f"Subscription assigned to {len(user_ids)} user(s).", "success")
                    return redirect(url_for("setup_wizard"))
                state["assignment"] = "skipped" if action == "skip" else state.get("assignment", "reviewed")

            elif step == 10:
                _save(db, step=10, state=state, active=0, completed=1)
                return redirect(url_for("dashboard"))

            settings = _settings(db)
            next_step = _next_step(db, step, state, settings)
            _save(db, step=next_step, state=state, active=1)
            return redirect(url_for("setup_wizard"))

        settings = _settings(db)
        state = _state(settings)
        page_data = load_setup_wizard_page_data(db, settings, state)
        communications_available = _communications_available(settings, state)
        lang = session.get("lang") or settings.get("default_language") or "en"
        return render_template(
            "setup/wizard.html",
            step=step, total_steps=TOTAL_STEPS, copy=COPY.get(lang, COPY["en"]),
            state=state, settings=settings,
            languages=get_available_languages(),
            communications_available=communications_available,
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
