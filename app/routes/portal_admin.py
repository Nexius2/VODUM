from flask import current_app, flash, redirect, render_template, request, url_for, jsonify

from core.i18n import get_translator
from core.auth_principal import admin_required
from core.portal_settings import normalize_portal_settings
from core.portal_local_auth import create_local_invitation, revoke_invitation
from core.portal_audit import record_portal_event
from core.portal_readiness import evaluate_portal_readiness
from core.portal_admin_data import apply_portal_admin_action
from core.portal_email import portal_email_payload
from core.portal_privacy import erase_portal_user_data, export_portal_user_data
from core.portal_page_data import (
    load_portal_home, load_portal_media_access, load_portal_monitoring,
    load_portal_profile, load_portal_subscription, load_portal_support,
)
from core.portal_auth_methods import list_auth_methods
from core.portal_messages import add_message, list_messages, mark_read, notify_user_of_admin_reply
from core.i18n import get_available_languages
from web.helpers import add_log, get_db, send_email_via_settings


PORTAL_SETTINGS_COLUMNS = """
    portal_enabled,
    portal_local_test_enabled,
    portal_public_url,
    portal_allowed_hostname,
    portal_show_subscription,portal_show_media_access,portal_show_monitoring,portal_show_support,portal_show_payment,
    portal_support_content,portal_show_support_email,portal_quick_messages_enabled,
    portal_payment_url,portal_payment_label,
    portal_local_auth_enabled,
    portal_plex_auth_enabled,
    portal_jellyfin_auth_enabled
"""
PORTAL_READINESS_COLUMNS = """
    portal_enabled,portal_public_url,portal_allowed_hostname,brand_name,contact_email,
    portal_show_subscription,portal_show_media_access,portal_show_monitoring,portal_show_support,portal_show_payment,
    portal_support_content,portal_show_support_email,portal_quick_messages_enabled,
    portal_payment_url,portal_payment_label,
    portal_local_auth_enabled,portal_plex_auth_enabled,portal_jellyfin_auth_enabled,
    portal_password_min_length,portal_password_require_upper,portal_password_require_lower,
    portal_password_require_digit,portal_password_require_symbol,
    mailing_enabled,smtp_host,smtp_user,mail_from,web_secure_cookies,web_trust_proxy
"""


def register(app):
    @app.context_processor
    def portal_message_badge_context():
        if not request.path.startswith("/communications"):
            return {}
        try:
            row = get_db().query_one(
                "SELECT COUNT(*) AS cnt FROM portal_messages WHERE sender_type='user' AND read_by_admin=0"
            )
        except Exception:
            return {}
        return {"unread_total": int(row["cnt"] or 0) if row else 0}

    @app.get("/communications/messages")
    @admin_required
    def portal_messages_admin_page():
        db = get_db()
        conversations = [dict(row) for row in (db.query(
            """SELECT c.id,c.status,c.updated_at,vu.id AS vodum_user_id,vu.username,vu.email,
                      SUM(CASE WHEN m.sender_type='user' AND m.read_by_admin=0 THEN 1 ELSE 0 END) AS unread,
                      MAX(m.created_at) AS last_message_at
               FROM portal_conversations c JOIN portal_accounts pa ON pa.id=c.portal_account_id
               JOIN vodum_users vu ON vu.id=pa.vodum_user_id LEFT JOIN portal_messages m ON m.conversation_id=c.id
               GROUP BY c.id ORDER BY COALESCE(MAX(m.created_at),c.updated_at) DESC"""
        ) or [])]
        selected_id = request.args.get("conversation", type=int)
        selected = next((row for row in conversations if row["id"] == selected_id), None)
        if selected is None and conversations:
            selected = conversations[0]
        messages = []
        if selected:
            messages = list_messages(db, selected["id"])
            mark_read(db, selected["id"], "admin")
            selected["unread"] = 0
        unread_total = sum(int(row.get("unread") or 0) for row in conversations)
        return render_template("communications/communications_messages.html", conversations=conversations,
            selected=selected, messages=messages, unread_total=unread_total, current_subpage="messages")

    @app.post("/communications/messages/<int:conversation_id>/reply")
    @admin_required
    def portal_messages_admin_reply(conversation_id):
        db = get_db()
        if not db.query_one("SELECT id FROM portal_conversations WHERE id=?", (conversation_id,)):
            flash("portal_message_conversation_missing", "error")
            return redirect(url_for("portal_messages_admin_page"))
        try:
            add_message(db, conversation_id, "admin", request.form.get("body"))
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            try:
                notify_user_of_admin_reply(db, conversation_id)
            except Exception:
                current_app.logger.exception("Unable to notify portal user for conversation %s", conversation_id)
            flash("portal_message_sent", "success")
        return redirect(url_for("portal_messages_admin_page", conversation=conversation_id))

    @app.get("/users/<int:user_id>/portal/export")
    @admin_required
    def portal_user_export(user_id):
        payload = export_portal_user_data(get_db(), user_id)
        if not payload:
            return jsonify({"error": "user_not_found"}), 404
        response = jsonify(payload)
        response.headers["Content-Disposition"] = f'attachment; filename="vodum-portal-user-{user_id}.json"'
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/users/<int:user_id>/portal/erase")
    @admin_required
    def portal_user_erase(user_id):
        erased = erase_portal_user_data(get_db(), user_id)
        flash("portal_data_erased" if erased else "portal_not_invited", "success" if erased else "error")
        return redirect(url_for("user_detail", user_id=user_id))

    @app.post("/users/<int:user_id>/portal/action")
    @admin_required
    def portal_user_action(user_id):
        action = str(request.form.get("action") or "")
        event_names = {
            "revoke_invitation": "admin_invitation_revoked", "suspend": "admin_account_suspended",
            "reactivate": "admin_account_reactivated", "force_logout": "admin_forced_logout",
            "reset_auth": "admin_auth_reset",
        }
        try:
            account_id = apply_portal_admin_action(get_db(), user_id, action)
            record_portal_event(get_db(), event_names[action], "success", portal_account_id=account_id)
            if action in {"suspend", "reactivate", "reset_auth"}:
                mail_event = {"suspend": "suspended", "reactivate": "reactivated", "reset_auth": "authentication_changed"}[action]
                payload = portal_email_payload(get_db(), user_id, mail_event)
                if payload:
                    send_email_via_settings(payload["to"], payload["subject"], payload["body"])
            flash("portal_admin_action_done", "success")
        except (ValueError, KeyError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("user_detail", user_id=user_id))

    @app.post("/users/<int:user_id>/portal/invite")
    @admin_required
    def portal_user_invite(user_id):
        db = get_db()
        user = db.query_one("SELECT id,email,username FROM vodum_users WHERE id=?", (user_id,))
        settings = db.query_one(
            "SELECT portal_public_url,portal_local_auth_enabled FROM settings WHERE id=1"
        )
        if not user or not (user["email"] or "").strip():
            flash("portal_invite_email_required", "error")
            return redirect(url_for("user_detail", user_id=user_id))
        if not settings or int(settings["portal_local_auth_enabled"] or 0) != 1:
            flash("portal_local_auth_disabled", "error")
            return redirect(url_for("user_detail", user_id=user_id))
        public_url = (settings["portal_public_url"] or "").strip().rstrip("/")
        if not public_url:
            flash("portal_public_url_required", "error")
            return redirect(url_for("user_detail", user_id=user_id))
        try:
            invitation = create_local_invitation(db, user_id, user["email"])
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("user_detail", user_id=user_id))
        activation_url = f"{public_url}/portal/activate?token={invitation['token']}"
        payload = portal_email_payload(db, user_id, "invitation", {"url": activation_url})
        if not payload or not send_email_via_settings(payload["to"], payload["subject"], payload["body"]):
            revoke_invitation(db, invitation["token"])
            flash("portal_invite_send_failed", "error")
            return redirect(url_for("user_detail", user_id=user_id))
        add_log("info", "portal", f"Portal invitation sent for user #{user_id}")
        record_portal_event(db, "invitation_sent", "success", portal_account_id=invitation["portal_account_id"])
        flash("portal_invite_sent", "success")
        return redirect(url_for("user_detail", user_id=user_id))

    @app.get("/settings/portal")
    @admin_required
    def portal_settings_page():
        db = get_db()
        settings = db.query_one(
            f"SELECT {PORTAL_READINESS_COLUMNS} FROM settings WHERE id = 1"
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect(url_for("settings_page"))
        readiness = evaluate_portal_readiness(dict(settings), trusted_proxy_networks=current_app.config.get("TRUSTED_PROXY_NETS", ""))
        public_url = str(settings["portal_public_url"] or "").strip().rstrip("/")
        return render_template(
            "settings/portal.html",
            settings=dict(settings),
            active_page="portal_settings",
            portal_runtime_ready=readiness["ready"],
            portal_readiness=readiness,
            portal_login_url=f"{public_url}/portal/login" if public_url else "",
        )

    @app.get("/settings/portal/users/search")
    @admin_required
    def portal_admin_user_search():
        db = get_db()
        term = str(request.args.get("q") or "").strip()[:100]
        if len(term) < 2:
            return jsonify({"users": []})
        pattern = f"%{term}%"
        rows = db.query(
            "SELECT id,username,email,firstname,lastname FROM vodum_users "
            "WHERE username LIKE ? OR email LIKE ? OR firstname LIKE ? OR lastname LIKE ? "
            "ORDER BY LOWER(COALESCE(username,email,firstname,'')),id LIMIT 20",
            (pattern, pattern, pattern, pattern),
        ) or []
        return jsonify({"users": [dict(row) for row in rows]})

    @app.get("/settings/portal/preview/<int:user_id>/<page>")
    @admin_required
    def portal_admin_user_preview(user_id, page="home"):
        db = get_db()
        home = load_portal_home(db, int(user_id))
        profile = load_portal_profile(db, int(user_id))
        if not home or not profile:
            flash("portal_admin_user_invalid", "error")
            return redirect(url_for("portal_settings_page"))
        settings = dict(db.query_one(
            "SELECT brand_name,portal_logo_url,portal_show_subscription,portal_show_media_access,"
            "portal_show_monitoring,portal_show_support,user_notifications_can_override "
            "FROM settings WHERE id=1"
        ) or {})
        features = {
            "subscription": bool(settings.get("portal_show_subscription")),
            "media": bool(settings.get("portal_show_media_access")),
            "monitoring": bool(settings.get("portal_show_monitoring")),
            "support": bool(settings.get("portal_show_support")),
        }
        common = dict(
            portal_brand_name=settings.get("brand_name"), portal_logo_url=settings.get("portal_logo_url"),
            portal_terms_url=None, portal_privacy_url=None,
            admin_preview=True, preview_user_id=int(user_id), portal_features=features,
        )
        if page == "home":
            return render_template("portal/home.html", **home, **common, active_portal_page="home")
        if page == "profile":
            account = db.query_one("SELECT id FROM portal_accounts WHERE vodum_user_id=?", (int(user_id),))
            auth_methods = list_auth_methods(db, int(account["id"])) if account else []
            servers = [dict(row) for row in (db.query("SELECT id,name FROM servers WHERE LOWER(type)='jellyfin' ORDER BY name,id") or [])]
            return render_template("portal/profile.html", profile=profile, auth_methods=auth_methods,
                jellyfin_servers=servers, recently_reauthenticated=False, languages=get_available_languages(),
                notifications_can_override=bool(settings.get("user_notifications_can_override")),
                **common, active_portal_page="profile")
        if page == "subscription" and features["subscription"]:
            return render_template("portal/subscription.html", subscription=load_portal_subscription(db, user_id), **common, active_portal_page="subscription")
        if page == "media" and features["media"]:
            return render_template("portal/media_access.html", accounts=load_portal_media_access(db, user_id), **common, active_portal_page="media")
        if page == "monitoring" and features["monitoring"]:
            return render_template("portal/monitoring.html", monitoring=load_portal_monitoring(db, user_id), **common, active_portal_page="monitoring")
        if page == "support" and features["support"]:
            support = load_portal_support(db, user_id)
            if support:
                return render_template("portal/support.html", support=support, **common, active_portal_page="support")
        flash("portal_preview_page_unavailable", "error")
        return redirect(url_for("portal_admin_user_preview", user_id=user_id, page="home"))

    @app.post("/settings/portal")
    @admin_required
    def portal_settings_save():
        current = get_db().query_one(
            f"SELECT {PORTAL_READINESS_COLUMNS} FROM settings WHERE id = 1"
        )
        preview = normalize_portal_settings(request.form, activation_ready=True)
        candidate = dict(current or {})
        candidate.update(preview.values)
        readiness = evaluate_portal_readiness(candidate, trusted_proxy_networks=current_app.config.get("TRUSTED_PROXY_NETS", ""))
        result = normalize_portal_settings(request.form, activation_ready=readiness["ready"])
        if result.errors:
            translator = get_translator()
            for error in result.errors:
                flash(translator(error), "error")
            return redirect(url_for("portal_settings_page"))

        get_db().execute(
            """
            UPDATE settings SET
                portal_enabled = :portal_enabled,
                portal_local_test_enabled = :portal_local_test_enabled,
                portal_public_url = :portal_public_url,
                portal_allowed_hostname = :portal_allowed_hostname,
                portal_show_subscription = :portal_show_subscription,
                portal_show_media_access = :portal_show_media_access,
                portal_show_monitoring = :portal_show_monitoring,
                portal_show_support = :portal_show_support,
                portal_support_content = :portal_support_content,
                portal_show_support_email = :portal_show_support_email,
                portal_quick_messages_enabled = :portal_quick_messages_enabled,
                portal_show_payment = :portal_show_payment,
                portal_payment_url = :portal_payment_url,
                portal_payment_label = :portal_payment_label,
                portal_local_auth_enabled = :portal_local_auth_enabled,
                portal_plex_auth_enabled = :portal_plex_auth_enabled,
                portal_jellyfin_auth_enabled = :portal_jellyfin_auth_enabled
                ,portal_password_min_length = :portal_password_min_length
                ,portal_password_require_upper = :portal_password_require_upper
                ,portal_password_require_lower = :portal_password_require_lower
                ,portal_password_require_digit = :portal_password_require_digit
                ,portal_password_require_symbol = :portal_password_require_symbol
            WHERE id = 1
            """,
            result.values,
        )
        add_log("info", "settings", "User portal settings updated", {
            "enabled": bool(result.values["portal_enabled"]),
            "local_test": bool(result.values["portal_local_test_enabled"]),
            "local_auth": bool(result.values["portal_local_auth_enabled"]),
            "plex_auth": bool(result.values["portal_plex_auth_enabled"]),
            "jellyfin_auth": bool(result.values["portal_jellyfin_auth_enabled"]),
        })
        flash("portal_settings_saved", "success")
        return redirect(url_for("portal_settings_page"))
