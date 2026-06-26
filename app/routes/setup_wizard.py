from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from core.app_paths import imports_dir as get_imports_dir

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from core.i18n import get_available_languages
from core.server_validation import validate_media_server
from core.auth_totp import generate_totp_secret, provisioning_uri, verify_totp_code
from secret_store import encrypt_secret, encrypt_server_settings_json
from tasks_engine import enable_and_run_task_by_name, enqueue_server_discovery_sequence, ensure_tasks_enabled
from web.helpers import get_db


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
        "title": "Installation de VODUM", "step": "Ã‰tape", "continue": "Continuer",
        "back": "Retour", "skip": "Configurer plus tard", "finish": "Commencer Ã  utiliser VODUM",
        "configure": "Configurer maintenant", "new": "CrÃ©er une nouvelle instance", "restore": "Restaurer une sauvegarde",
        "admin": "Compte administrateur", "localization": "Localisation",
        "servers": "Serveurs multimÃ©dias", "communications": "Communications",
        "messages": "ModÃ¨les de messages", "subscriptions": "Abonnements",
        "subscription_settings": "ParamÃ¨tres des abonnements", "assignment": "Attribution des abonnements",
        "summary": "Installation terminÃ©e", "required": "Au moins un serveur Plex ou Jellyfin validÃ© est obligatoire.",
        "sync": "La synchronisation dÃ©marre en arriÃ¨re-plan et ne bloque pas lâ€™installation.",
        "saved": "La progression est enregistrÃ©e automatiquement aprÃ¨s chaque Ã©tape.",
    },
    "es": {
        "title": "InstalaciÃ³n de VODUM", "step": "Paso", "continue": "Continuar", "back": "AtrÃ¡s",
        "skip": "Configurar mÃ¡s tarde", "finish": "Empezar a usar VODUM", "configure": "Configurar ahora",
        "new": "Crear nueva instancia", "restore": "Restaurar copia", "admin": "Cuenta administradora",
        "localization": "LocalizaciÃ³n", "servers": "Servidores multimedia", "communications": "Comunicaciones",
        "messages": "Plantillas de mensajes", "subscriptions": "Suscripciones",
        "subscription_settings": "Ajustes de suscripciÃ³n", "assignment": "AsignaciÃ³n de suscripciones",
        "summary": "InstalaciÃ³n terminada", "required": "Se requiere al menos un servidor Plex o Jellyfin validado.",
        "sync": "La sincronizaciÃ³n continÃºa en segundo plano.", "saved": "El progreso se guarda automÃ¡ticamente.",
    },
    "de": {
        "title": "VODUM-Installation", "step": "Schritt", "continue": "Weiter", "back": "ZurÃ¼ck",
        "skip": "SpÃ¤ter konfigurieren", "finish": "VODUM verwenden", "configure": "Jetzt konfigurieren",
        "new": "Neue Instanz erstellen", "restore": "Sicherung wiederherstellen", "admin": "Administratorkonto",
        "localization": "Lokalisierung", "servers": "Medienserver", "communications": "Kommunikation",
        "messages": "Nachrichtenvorlagen", "subscriptions": "Abonnements",
        "subscription_settings": "Abonnementeinstellungen", "assignment": "Abonnements zuweisen",
        "summary": "Installation abgeschlossen", "required": "Mindestens ein validierter Plex- oder Jellyfin-Server ist erforderlich.",
        "sync": "Die Synchronisierung lÃ¤uft im Hintergrund.", "saved": "Der Fortschritt wird automatisch gespeichert.",
    },
    "it": {
        "title": "Installazione VODUM", "step": "Passaggio", "continue": "Continua", "back": "Indietro",
        "skip": "Configura piÃ¹ tardi", "finish": "Inizia a usare VODUM", "configure": "Configura ora",
        "new": "Crea nuova istanza", "restore": "Ripristina backup", "admin": "Account amministratore",
        "localization": "Localizzazione", "servers": "Server multimediali", "communications": "Comunicazioni",
        "messages": "Modelli messaggio", "subscriptions": "Abbonamenti",
        "subscription_settings": "Impostazioni abbonamento", "assignment": "Assegnazione abbonamenti",
        "summary": "Installazione completata", "required": "Ãˆ richiesto almeno un server Plex o Jellyfin convalidato.",
        "sync": "La sincronizzazione continua in background.", "saved": "I progressi vengono salvati automaticamente.",
    },
}


def _settings(db) -> dict:
    return dict(db.query_one("SELECT * FROM settings WHERE id = 1") or {})


def _state(settings: dict) -> dict:
    try:
        value = json.loads(settings.get("wizard_state_json") or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(db, *, step: int | None = None, state: dict | None = None, active: int | None = None, completed: int | None = None):
    current = _settings(db)
    db.execute(
        """
        UPDATE settings SET
          wizard_step = ?,
          wizard_state_json = ?,
          wizard_active = ?,
          wizard_completed = ?
        WHERE id = 1
        """,
        (
            max(1, min(TOTAL_STEPS, int(step if step is not None else current.get("wizard_step") or 1))),
            json.dumps(state if state is not None else _state(current)),
            int(active if active is not None else current.get("wizard_active") or 0),
            int(completed if completed is not None else current.get("wizard_completed") or 0),
        ),
    )


def _communications_available(settings: dict, state: dict) -> bool:
    if state.get("communications") == "skipped":
        return False
    return bool(int(settings.get("mailing_enabled") or 0) or int(settings.get("discord_enabled") or 0))


def _step_available(db, step: int, state: dict, settings: dict | None = None) -> bool:
    settings = settings or _settings(db)
    if step == 6:
        return _communications_available(settings, state)

    subscriptions = int((db.query_one("SELECT COUNT(*) AS cnt FROM subscription_templates") or {"cnt": 0})["cnt"] or 0)
    if step in (8, 9) and (subscriptions == 0 or state.get("subscriptions") == "skipped"):
        return False
    if step == 9:
        users = int((db.query_one("SELECT COUNT(*) AS cnt FROM vodum_users") or {"cnt": 0})["cnt"] or 0)
        return users > 0
    return True


def _next_step(db, current_step: int, state: dict, settings: dict | None = None) -> int:
    settings = settings or _settings(db)
    for candidate in range(current_step + 1, TOTAL_STEPS + 1):
        if _step_available(db, candidate, state, settings):
            return candidate
        if candidate == 6:
            state["messages"] = "skipped"
        elif candidate == 8:
            state["subscription_settings"] = "skipped"
        elif candidate == 9:
            state["assignment"] = "skipped"
    return TOTAL_STEPS


def _previous_step(db, current_step: int, state: dict, settings: dict | None = None) -> int:
    settings = settings or _settings(db)
    for candidate in range(current_step - 1, 0, -1):
        if _step_available(db, candidate, state, settings):
            return candidate
    return 1


def _display_step(db, settings: dict, state: dict) -> int:
    step = max(1, min(TOTAL_STEPS, int(settings.get("wizard_step") or 1)))
    return step if _step_available(db, step, state, settings) else _next_step(db, step, state, settings)


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
                    path = imports_dir / f"restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{suffix}"
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
                    server_type = (request.form.get("server_type") or "").strip().lower()
                    url = (
                        request.form.get("media_server_base_address")
                        or request.form.get("server_url")
                        or request.form.get("url")
                        or ""
                    ).strip().rstrip("/")
                    token = (
                        request.form.get("media_server_access_token")
                        or request.form.get("server_token")
                        or request.form.get("token")
                        or ""
                    ).strip()
                    if server_type not in {"plex", "jellyfin"} or not url.startswith(("http://", "https://")) or not token:
                        flash("Provider, URL and token are required.", "error")
                        return redirect(url_for("setup_wizard"))
                    candidate = {"url": url, "local_url": None, "public_url": None, "settings_json": '{"verify_tls": true}'}
                    result = validate_media_server(server_type, url, token, server=candidate)
                    if result[0] != "up":
                        flash(f"Connection failed: {result[3]}", "error")
                        return redirect(url_for("setup_wizard"))
                    cursor = db.execute(
                        """
                        INSERT INTO servers(name,type,server_identifier,url,token,settings_json,status,server_version)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            result[1] or server_type.upper(),
                            server_type,
                            result[2] or str(uuid.uuid4()),
                            url,
                            encrypt_secret(token),
                            encrypt_server_settings_json('{"verify_tls": true}'),
                            "up",
                            result[3],
                        ),
                    )
                    server_id = int(cursor.lastrowid)
                    if server_type == "plex":
                        ensure_tasks_enabled(["check_servers", "sync_plex", "update_user_status"])
                    elif server_type == "jellyfin":
                        ensure_tasks_enabled(["check_servers", "sync_jellyfin", "update_user_status"])
                    else:
                        ensure_tasks_enabled(["check_servers", "update_user_status"])

                    enqueue_server_discovery_sequence(server_type)
                    state["media_server"] = "configured"
                    validated_ids = _validated_server_ids(state)
                    validated_ids.add(server_id)
                    state["validated_server_ids"] = sorted(validated_ids)
                    _save(db, step=4, state=state, active=1)
                    flash("Connection successful. Synchronization started in the background.", "success")
                    return redirect(url_for("setup_wizard"))
                validated_ids = _validated_server_ids(state)
                validated_count = 0
                if validated_ids:
                    placeholders = ",".join("?" for _ in validated_ids)
                    row = db.query_one(
                        f"SELECT COUNT(*) AS cnt FROM servers WHERE id IN ({placeholders})",
                        tuple(sorted(validated_ids)),
                    )
                    validated_count = int((row or {"cnt": 0})["cnt"] or 0)
                elif state.get("media_server") == "configured":
                    validated_count = int(
                        (db.query_one("SELECT COUNT(*) AS cnt FROM servers") or {"cnt": 0})["cnt"] or 0
                    )
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
        validated_ids = _validated_server_ids(state)
        servers = [dict(x) for x in (db.query("SELECT id,name,type,url,status FROM servers ORDER BY id") or [])]
        for server in servers:
            server["wizard_validated"] = (
                int(server["id"]) in validated_ids
                or (not validated_ids and state.get("media_server") == "configured")
            )
        subscription_count = int((db.query_one("SELECT COUNT(*) AS cnt FROM subscription_templates") or {"cnt": 0})["cnt"] or 0)
        user_count = int((db.query_one("SELECT COUNT(*) AS cnt FROM vodum_users") or {"cnt": 0})["cnt"] or 0)
        sync_running = bool(db.query_one("SELECT id FROM tasks WHERE name IN ('sync_plex','sync_jellyfin') AND status IN ('queued','running') LIMIT 1"))
        communications_available = _communications_available(settings, state)
        communication_settings = dict(settings)
        communication_settings["smtp_pass_configured"] = bool(communication_settings.get("smtp_pass"))
        communication_settings["smtp_oauth_access_token_configured"] = bool(communication_settings.get("smtp_oauth_access_token"))
        communication_settings["discord_bot_token_configured"] = bool(communication_settings.get("discord_bot_token"))
        communication_settings["smtp_pass"] = ""
        communication_settings["smtp_oauth_access_token"] = ""
        communication_settings["discord_bot_token"] = ""
        wizard_templates = [
            dict(row) for row in (db.query(
                """
                SELECT id,key,name,enabled,subject,body FROM comm_templates
                WHERE key IN ('default_relance','default_fin','stream_blocked','usage_risk_upgrade_suggestion')
                ORDER BY CASE key
                  WHEN 'default_relance' THEN 1 WHEN 'default_fin' THEN 2
                  WHEN 'stream_blocked' THEN 3 ELSE 4 END
                """
            ) or [])
        ]
        subscription_templates = [
            dict(row) for row in (db.query(
                "SELECT id,name,duration_days,is_lifetime,is_enabled FROM subscription_templates ORDER BY is_default DESC,name"
            ) or [])
        ]
        wizard_users = [
            dict(row) for row in (db.query(
                """
                SELECT u.id,u.username,u.email,u.subscription_template_id,st.name AS subscription_name
                FROM vodum_users u
                LEFT JOIN subscription_templates st ON st.id=u.subscription_template_id
                ORDER BY COALESCE(u.username,u.email),u.id LIMIT 500
                """
            ) or [])
        ]
        lang = session.get("lang") or settings.get("default_language") or "en"
        return render_template(
            "setup/wizard.html",
            step=step, total_steps=TOTAL_STEPS, copy=COPY.get(lang, COPY["en"]),
            state=state, settings=settings, servers=servers,
            languages=get_available_languages(), subscription_count=subscription_count,
            user_count=user_count, sync_running=sync_running, communication_settings=communication_settings,
            wizard_templates=wizard_templates, subscription_templates=subscription_templates, wizard_users=wizard_users,
            communications_available=communications_available,
        )

    @app.get("/setup")
    def setup_wizard_page():
        return setup_wizard()

    @app.post("/setup/restart")
    def setup_wizard_restart():
        db = get_db()
        _save(db, step=1, state={}, active=1, completed=0)
        return redirect(url_for("setup_wizard"))

