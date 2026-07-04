# Auto-split from app.py (keep URLs/endpoints intact)
import json

from flask import (
    render_template, g, request, redirect, url_for, flash, session, current_app,
)

from logging_utils import get_logger
from core.i18n import get_translator, get_available_languages
from werkzeug.security import generate_password_hash, check_password_hash

from tasks_engine import apply_cron_master_switch, sync_expiry_tasks_from_settings, force_task_run, mark_auto_enable_dirty
from web.helpers import get_db, add_log
from secret_store import encryption_key_status, encrypt_secret
from core.auth_totp import generate_totp_secret, provisioning_uri, verify_totp_code

settings_logger = get_logger("settings")

SETTINGS_PAGE_COLUMNS = """
    id,
    default_language,
    timezone,
    admin_email,
    contact_email,
    brand_name,
    default_subscription_days,
    delete_after_expiry_days,
    expiry_mode,
    warn_then_disable_days,
    preavis_days,
    reminder_days,
    enable_cron_jobs,
    maintenance_mode,
    debug_mode,
    web_secure_cookies,
    web_cookie_samesite,
    web_trust_proxy,
    plex_user_import_mode,
    enable_anonymous_telemetry,
    admin_totp_enabled
"""


def register(app):
    @app.route("/settings", methods=["GET"])
    def settings_page():
        db = get_db()

        # ------------------------------
        # Charger settings (source unique)
        # ------------------------------
        settings = db.query_one(
            f"SELECT {SETTINGS_PAGE_COLUMNS} FROM settings WHERE id = 1"
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        settings = dict(settings)
        totp_enabled = int(settings.get("admin_totp_enabled") or 0) == 1
        pending_totp_secret = "" if totp_enabled else generate_totp_secret()
        pending_totp_uri = provisioning_uri(pending_totp_secret, settings.get("admin_email") or "admin") if pending_totp_secret else ""

        return render_template(
            "settings/settings.html",
            settings=settings,
            active_page="settings",
            current_lang=session.get("lang", settings["default_language"]),
            available_languages=get_available_languages(),
            app_version=g.get("app_version", "dev"),
            encryption_key_status=encryption_key_status(),
            pending_totp_secret=pending_totp_secret,
            pending_totp_uri=pending_totp_uri,
        )

    @app.route("/settings/save", methods=["POST"])
    def settings_save():
        db = get_db()


        # plex user gathering mode
        plex_user_import_mode = request.form.get(
            "plex_user_import_mode",
            "global"
        ).strip().lower()

        if plex_user_import_mode not in ("global", "shared_only"):
            plex_user_import_mode = "global"

        # ------------------------------
        # Charger settings (source unique)
        # ------------------------------
        settings = db.query_one(
            f"SELECT {SETTINGS_PAGE_COLUMNS} FROM settings WHERE id = 1"
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        settings = dict(settings)

        def _sanitize_notifications_order(raw: str) -> str:
            allowed = {"email", "discord"}
            raw = (raw or "").strip().lower()
            if not raw:
                return "email"

            parts = [p.strip() for p in raw.split(",") if p.strip()]
            cleaned = []
            for p in parts:
                if p in allowed and p not in cleaned:
                    cleaned.append(p)

            if not cleaned:
                return "email"
            if len(cleaned) == 1:
                return cleaned[0]
            return f"{cleaned[0]},{cleaned[1]}"

        # --------------------------------------------------
        # Expiration handling (2 exclusive modes)
        # --------------------------------------------------
        expiry_mode = (request.form.get("expiry_mode") or settings.get("expiry_mode") or "none").strip()
        if expiry_mode not in ("none", "warn_only", "warn_then_disable", "disable"):
            expiry_mode = "none"

        warn_then_disable_days_raw = (request.form.get("warn_then_disable_days") or settings.get("warn_then_disable_days") or 7)
        try:
            warn_then_disable_days = int(warn_then_disable_days_raw)
        except Exception:
            warn_then_disable_days = int(settings.get("warn_then_disable_days") or 7)

        # X days must be >= 1 (only meaningful for warn_then_disable)
        if warn_then_disable_days < 1:
            warn_then_disable_days = 1

        if expiry_mode not in ("warn_then_disable", "warn_only"):
            warn_then_disable_days = int(settings.get("warn_then_disable_days") or 7)

        old_enable_cron_jobs = 1 if int(settings.get("enable_cron_jobs") or 0) == 1 else 0

        new_values = {
            "default_language": request.form.get(
                "default_language", settings["default_language"]
            ),
            "timezone": request.form.get(
                "timezone", settings["timezone"]
            ),
            "contact_email": request.form.get(
                "contact_email", settings.get("contact_email") or settings.get("admin_email") or ""
            ),
            "default_subscription_days": request.form.get(
                "default_expiration_days",
                settings["default_subscription_days"],
            ),
            "delete_after_expiry_days": request.form.get(
                "delete_after_expiry_days",
                settings["delete_after_expiry_days"],
            ),
            "plex_user_import_mode": plex_user_import_mode,
            "enable_anonymous_telemetry": 1 if request.form.get("enable_anonymous_telemetry") == "on" else 0,
            # ✅ délais statut (settings ONLY)
            "preavis_days": request.form.get(
                "preavis_days",
                settings["preavis_days"],
            ),
            "reminder_days": request.form.get(
                "relance_days",
                settings["reminder_days"],
            ),
            "brand_name": request.form.get("brand_name", settings.get("brand_name")),

            "expiry_mode": expiry_mode,
            "warn_then_disable_days": warn_then_disable_days,
            # legacy flag kept for backward compatibility
            "disable_on_expiry": 1 if expiry_mode == "disable" else 0,
            "enable_cron_jobs": 1 if request.form.get("enable_cron_jobs") == "1" else 0,
            "maintenance_mode": 1 if request.form.get("maintenance_mode") == "1" else 0,
            "debug_mode": 1 if request.form.get("debug_mode") == "1" else 0,
            "web_secure_cookies": 1 if request.form.get("web_secure_cookies") == "1" else 0,
            "web_cookie_samesite": request.form.get(
                "web_cookie_samesite",
                settings.get("web_cookie_samesite") or "Lax"
            ),
            "web_trust_proxy": 1 if request.form.get("web_trust_proxy") == "1" else 0,
        }

        # --------------------------------------------------
        # Conversions INT (uniformes)
        # --------------------------------------------------
        for key in (
            "default_subscription_days",
            "delete_after_expiry_days",
            "preavis_days",
            "reminder_days",
            "warn_then_disable_days",
        ):
            try:
                new_values[key] = int(new_values[key])
            except Exception:
                new_values[key] = settings[key]

        if new_values["web_cookie_samesite"] not in ("Lax", "Strict", "None"):
            new_values["web_cookie_samesite"] = settings.get("web_cookie_samesite") or "Lax"

        # SameSite=None impose Secure=True sur les navigateurs modernes
        if new_values["web_cookie_samesite"] == "None":
            new_values["web_secure_cookies"] = 1

        # --------------------------------------------------
        # UPDATE settings (source unique)
        # --------------------------------------------------
        db.execute(
            """
            UPDATE settings SET
                default_language = :default_language,
                timezone = :timezone,
                contact_email = :contact_email,
                brand_name = :brand_name,
                default_subscription_days = :default_subscription_days,
                delete_after_expiry_days = :delete_after_expiry_days,
                expiry_mode = :expiry_mode,
                warn_then_disable_days = :warn_then_disable_days,
                preavis_days = :preavis_days,
                reminder_days = :reminder_days,
                disable_on_expiry = :disable_on_expiry,
                enable_cron_jobs = :enable_cron_jobs,
                maintenance_mode = :maintenance_mode,
                debug_mode = :debug_mode,
                web_secure_cookies = :web_secure_cookies,
                web_cookie_samesite = :web_cookie_samesite,
                web_trust_proxy = :web_trust_proxy,
                plex_user_import_mode = :plex_user_import_mode,
                enable_anonymous_telemetry = :enable_anonymous_telemetry
            WHERE id = 1
            """,
            new_values,
        )

        telemetry_enabled = int(new_values["enable_anonymous_telemetry"] or 0)
        db.execute(
            """
            UPDATE tasks
            SET enabled=?,
                status=CASE WHEN ?=1 THEN 'idle' ELSE 'disabled' END,
                next_run=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE name='send_telemetry'
            """,
            (telemetry_enabled, telemetry_enabled),
        )
        if not telemetry_enabled:
            db.execute(
                """
                UPDATE settings
                SET telemetry_last_sent_at=NULL
                WHERE id=1
                """
            )

        # Appliquer immédiatement au process Flask courant
        current_app.config["SESSION_COOKIE_SAMESITE"] = new_values["web_cookie_samesite"]
        current_app.config["SESSION_COOKIE_SECURE"] = bool(new_values["web_secure_cookies"]) or (
            new_values["web_cookie_samesite"] == "None"
        )
        current_app.config["TRUST_PROXY_ENABLED"] = bool(new_values["web_trust_proxy"])

        # --------------------------------------------------
        # MASTER scheduled tasks switch (enable_cron_jobs)
        # --------------------------------------------------
        if old_enable_cron_jobs != new_values["enable_cron_jobs"]:
            apply_cron_master_switch(new_values["enable_cron_jobs"])

        # --------------------------------------------------
        # Purge immédiate des policies système si on n'est plus en warn_then_disable
        # (évite d'attendre la prochaine exécution d'une tâche)
        # --------------------------------------------------
        if expiry_mode not in ("warn_then_disable", "warn_only"):
            try:
                rows = db.query("SELECT id, rule_value_json FROM stream_policies WHERE scope_type='user'") or []
                purged = 0
                for r in rows:
                    try:
                        rule = json.loads(r["rule_value_json"] or "{}")
                    except Exception:
                        rule = {}
                    if rule.get("system_tag") == "expired_subscription":
                        db.execute("DELETE FROM stream_policies WHERE id = ?", (int(r["id"]),))
                        purged += 1

                if purged:
                    settings_logger.info(f"Purged {purged} expired_subscription system policy(ies) after settings change")
            except Exception:
                settings_logger.error("Failed to purge expired_subscription policies after settings change", exc_info=True)


        # --------------------------------------------------
        # Wakeup tasks impacted by settings changes
        # --------------------------------------------------
        force_task_run("check_mailing_status")
        force_task_run("send_comm_campaigns")
        if telemetry_enabled:
            force_task_run("send_telemetry")

        mark_auto_enable_dirty()

        # --------------------------------------------------
        # Sync TASKS from SETTINGS (source unique)
        # --------------------------------------------------
        sync_expiry_tasks_from_settings(
            new_values.get("expiry_mode"),
            new_values["enable_cron_jobs"],
        )

        # --------------------------------------------------
        # Log cohérent
        # --------------------------------------------------
        add_log(
            "info",
            "settings",
            "Settings updated",
            {
                "default_language": new_values["default_language"],
                "default_subscription_days": new_values["default_subscription_days"],
                "preavis_days": new_values["preavis_days"],
                "reminder_days": new_values["reminder_days"],
            },
        )

        if new_values["default_language"] in get_available_languages():
            session["lang"] = new_values["default_language"]
        else:
            session.pop("lang", None)

        flash(get_translator()("settings_saved"), "success")
        return redirect(url_for("settings_page"))





    @app.route("/settings/security", methods=["POST"])
    def settings_security_save():
        db = get_db()
        settings = db.query_one(
            """
            SELECT admin_email, admin_password_hash, admin_totp_enabled, admin_totp_secret
            FROM settings
            WHERE id = 1
            """
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect(url_for("settings_page"))

        settings = dict(settings)
        current_password = request.form.get("current_password") or ""
        password_hash = settings.get("admin_password_hash") or ""
        if not password_hash or not check_password_hash(password_hash, current_password):
            flash("Mot de passe actuel incorrect.", "error")
            return redirect(url_for("settings_page"))

        admin_email = (request.form.get("admin_email") or "").strip().lower()
        if (
            not admin_email
            or " " in admin_email
            or admin_email.count("@") != 1
            or "." not in admin_email.split("@", 1)[1]
        ):
            flash("Email de connexion invalide.", "error")
            return redirect(url_for("settings_page"))

        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()
        password_update_sql = ""
        params = {
            "admin_email": admin_email,
            "admin_totp_enabled": int(settings.get("admin_totp_enabled") or 0),
            "admin_totp_secret": settings.get("admin_totp_secret"),
        }

        if new_password or confirm_password:
            if len(new_password) < 8:
                flash("Mot de passe admin trop court (8 caracteres minimum).", "error")
                return redirect(url_for("settings_page"))
            if new_password != confirm_password:
                flash("La confirmation du mot de passe ne correspond pas.", "error")
                return redirect(url_for("settings_page"))
            password_update_sql = ", admin_password_hash = :admin_password_hash"
            params["admin_password_hash"] = generate_password_hash(new_password)

        requested_totp = request.form.get("admin_totp_enabled") == "1"
        current_totp = int(settings.get("admin_totp_enabled") or 0) == 1

        if requested_totp and not current_totp:
            pending_secret = (request.form.get("pending_totp_secret") or "").strip()
            totp_code = request.form.get("totp_code") or ""
            if not pending_secret or not verify_totp_code(pending_secret, totp_code):
                flash("Code double authentification invalide.", "error")
                return redirect(url_for("settings_page"))
            params["admin_totp_enabled"] = 1
            params["admin_totp_secret"] = encrypt_secret(pending_secret)
        elif not requested_totp and current_totp:
            params["admin_totp_enabled"] = 0
            params["admin_totp_secret"] = None

        db.execute(
            f"""
            UPDATE settings
            SET admin_email = :admin_email,
                admin_totp_enabled = :admin_totp_enabled,
                admin_totp_secret = :admin_totp_secret
                {password_update_sql}
            WHERE id = 1
            """,
            params,
        )

        session["vodum_admin_email"] = admin_email
        flash("Securite de l'application mise a jour.", "success")
        return redirect(url_for("settings_page"))
    @app.route("/settings/<section>", methods=["GET"])
    def settings_section_page(section: str):
        # Legacy section URLs predate the unified settings page. Keeping them as
        # redirects avoids rendering templates that no longer exist.
        return redirect(url_for("settings_page"))


    # -----------------------------
    # LOGS
    # -----------------------------
    
    def paginate(logs, page, per_page=10):
        start = (page - 1) * per_page
        end = start + per_page
        total_pages = (len(logs) + per_page - 1) // per_page
        return logs[start:end], total_pages

    




