import time
from flask import abort, flash, g, redirect, render_template, request, session, url_for

from core.auth_principal import permission_required, portal_login_required, portal_user_required
from core.portal_page_data import (
    load_portal_home, load_portal_media_access, load_portal_monitoring,
    load_portal_profile, load_portal_subscription, load_portal_support,
    normalize_portal_profile, update_portal_profile,
)
from web.helpers import get_db, send_email_via_settings
from core.portal_messages import add_message, conversation_for_user, list_messages, mark_read, unread_messages_for_user
from core.portal_provider_profile import update_portal_provider_profile
from core.portal_auth_methods import list_auth_methods, local_reauthentication_valid, recently_reauthenticated, unlink_identity, link_identity
from core.portal_jellyfin_auth import authenticate_jellyfin_user, JellyfinPortalAuthError
from core.portal_provider_identity_state import row_media_identity_is_usable
from core.portal_local_auth import change_local_password
from core.portal_sessions import revoke_other_portal_sessions
from core.i18n import get_available_languages

_FEATURE_COLUMNS = {"subscription": "portal_show_subscription", "media": "portal_show_media_access", "monitoring": "portal_show_monitoring", "support": "portal_show_support"}


def _portal_ui(db) -> dict:
    row = db.query_one(
        "SELECT brand_name,portal_logo_url,"
        "portal_show_subscription,portal_show_media_access,portal_show_monitoring,portal_show_support FROM settings WHERE id=1"
    ) or {}
    values = dict(row)
    unread_messages = 0
    principal = getattr(g, "auth_principal", None) or {}
    if principal.get("vodum_user_id"):
        unread_messages = unread_messages_for_user(db, int(principal["vodum_user_id"]))
    return {
        "portal_brand_name": values.get("brand_name"), "portal_logo_url": values.get("portal_logo_url"),
        "portal_terms_url": None, "portal_privacy_url": None,
        "portal_features": {key: int(values.get(column, 1) if values.get(column) is not None else 1) == 1 for key, column in _FEATURE_COLUMNS.items()},
        "portal_unread_messages": unread_messages,
    }


def _require_feature(db, name: str) -> dict:
    ui = _portal_ui(db)
    if not ui["portal_features"].get(name, False):
        abort(404)
    return ui


def register(app):
    def _portal_error(message_key: str, status=404):
        return render_template("portal/error.html", message_key=message_key, **_portal_ui(get_db()), active_portal_page=""), status

    @app.get("/portal")
    @portal_login_required
    @permission_required("portal.home.read_own")
    @portal_user_required
    def portal_home():
        data = load_portal_home(get_db(), int(g.auth_principal["vodum_user_id"]))
        if not data:
            return _portal_error("portal_account_missing")
        return render_template("portal/home.html", **data, **_portal_ui(get_db()), active_portal_page="home")

    @app.get("/portal/profile")
    @portal_login_required
    @permission_required("portal.profile.read_own")
    @portal_user_required
    def portal_profile():
        db = get_db()
        user_id = int(g.auth_principal["vodum_user_id"])
        profile = load_portal_profile(db, user_id)
        if not profile:
            return _portal_error("portal_account_missing")
        account_id = int(g.auth_principal["account_id"])
        setting = dict(db.query_one(
            "SELECT user_notifications_can_override,portal_local_auth_enabled,portal_plex_auth_enabled,portal_jellyfin_auth_enabled,discord_enabled FROM settings WHERE id=1"
        ) or {})
        methods = list_auth_methods(db, account_id)
        media_rows = [dict(row) for row in (db.query(
            "SELECT mu.type,mu.server_id,mu.details_json FROM media_users mu WHERE mu.vodum_user_id=?",
            (user_id,),
        ) or [])]
        usable = [row for row in media_rows if row_media_identity_is_usable(row)]
        has_provider = lambda provider: any(str(row.get("type") or "").lower() == provider for row in usable)
        linked_providers = {str(method.get("provider") or "").lower() for method in methods}
        linked_jellyfin_server_ids = {int(method["provider_server_id"]) for method in methods if str(method.get("provider") or "").lower() == "jellyfin" and method.get("provider_server_id") is not None}
        jellyfin_server_ids = {int(row["server_id"]) for row in usable if str(row.get("type") or "").lower() == "jellyfin" and row.get("server_id") is not None}
        servers = [dict(row) for row in (db.query(
            "SELECT id,name FROM servers WHERE LOWER(type)='jellyfin' ORDER BY name,id"
        ) or []) if int(row["id"]) in jellyfin_server_ids and int(row["id"]) not in linked_jellyfin_server_ids]
        can_link_plex = bool(int(setting.get("portal_plex_auth_enabled") or 0) and has_provider("plex") and "plex" not in linked_providers)
        can_link_jellyfin = bool(int(setting.get("portal_jellyfin_auth_enabled") or 0) and servers)
        has_local = "local" in linked_providers and bool(int(setting.get("portal_local_auth_enabled") or 0))
        return render_template(
            "portal/profile.html", profile=profile, auth_methods=methods, jellyfin_servers=servers,
            has_local_auth=has_local, can_link_plex=can_link_plex, can_link_jellyfin=can_link_jellyfin,
            show_auth_management=bool(has_local or can_link_plex or can_link_jellyfin),
            recently_reauthenticated=recently_reauthenticated(session), languages=get_available_languages(),
            notifications_can_override=True, discord_enabled=bool(int(setting.get("discord_enabled") or 0)),
            **_portal_ui(db), active_portal_page="profile",
        )

    @app.post("/portal/profile/methods/reauthenticate")
    @portal_login_required
    @portal_user_required
    def portal_methods_reauthenticate():
        if local_reauthentication_valid(get_db(), int(g.auth_principal["account_id"]), request.form.get("password") or ""):
            session["portal_reauthenticated_at"] = int(time.time()); flash("portal_reauthentication_done", "success")
        else:
            flash("portal_reauthentication_failed", "error")
        return redirect(url_for("portal_profile"))

    @app.post("/portal/profile/methods/jellyfin")
    @portal_login_required
    @portal_user_required
    def portal_method_link_jellyfin():
        try:
            identity = authenticate_jellyfin_user(get_db(), int(request.form.get("server_id") or 0), request.form.get("username") or "", request.form.get("password") or "")
            link_identity(get_db(), int(g.auth_principal["account_id"]), "jellyfin", identity.subject, server_id=identity.server_id, identifier=identity.username)
            session["portal_reauthenticated_at"] = int(time.time()); flash("portal_method_linked", "success")
        except (JellyfinPortalAuthError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("portal_profile"))

    @app.post("/portal/profile/methods/<int:identity_id>/unlink")
    @portal_login_required
    @portal_user_required
    def portal_method_unlink(identity_id):
        try:
            if not recently_reauthenticated(session): raise ValueError("portal_reauthentication_required")
            unlink_identity(get_db(), int(g.auth_principal["account_id"]), identity_id)
            flash("portal_method_unlinked", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("portal_profile"))

    @app.post("/portal/profile")
    @portal_login_required
    @permission_required("portal.profile.update_own")
    @portal_user_required
    def portal_profile_save():
        db = get_db()
        values, errors = normalize_portal_profile(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("portal_profile"))
        setting = db.query_one("SELECT discord_enabled FROM settings WHERE id=1") or {}
        discord_enabled = bool(int(dict(setting).get("discord_enabled") or 0))
        update_portal_profile(
            db, int(g.auth_principal["vodum_user_id"]), values,
            notifications_can_override=True, discord_enabled=discord_enabled,
        )
        if values.get("preferred_language"):
            session["lang"] = values["preferred_language"]
        flash("portal_profile_saved", "success")
        return redirect(url_for("portal_profile"))

    @app.post("/portal/profile/password")
    @portal_login_required
    @portal_user_required
    def portal_password_change():
        new_password = request.form.get("new_password") or ""
        try:
            if new_password != (request.form.get("new_password_confirm") or ""):
                raise ValueError("portal_password_mismatch")
            change_local_password(get_db(), int(g.auth_principal["account_id"]), request.form.get("current_password") or "", new_password)
            revoke_other_portal_sessions(get_db(), int(g.auth_principal["account_id"]), int(g.auth_principal["portal_session_id"]), reason="password_changed")
            session["portal_reauthenticated_at"] = int(time.time())
            flash("portal_password_changed", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("portal_profile"))

    @app.get("/portal/subscription")
    @portal_login_required
    @permission_required("portal.subscription.read_own")
    @portal_user_required
    def portal_subscription():
        db = get_db(); ui = _require_feature(db, "subscription")
        subscription = load_portal_subscription(
            db, int(g.auth_principal["vodum_user_id"]), include_available_plans=True
        )
        if not subscription:
            return _portal_error("portal_account_missing")
        return render_template("portal/subscription.html", subscription=subscription, **ui, active_portal_page="subscription")

    @app.get("/portal/media-access")
    @portal_login_required
    @permission_required("portal.media_access.read_own")
    @portal_user_required
    def portal_media_access():
        db = get_db(); ui = _require_feature(db, "media")
        accounts = load_portal_media_access(db, int(g.auth_principal["vodum_user_id"]))
        return render_template("portal/media_access.html", accounts=accounts, **ui, active_portal_page="media")

    @app.post("/portal/media-access/<int:media_user_id>/profile")
    @portal_login_required
    @permission_required("portal.media_access.update_own")
    @portal_user_required
    def portal_media_profile_save(media_user_id):
        _require_feature(get_db(), "media")
        try:
            update_portal_provider_profile(get_db(), int(g.auth_principal["vodum_user_id"]), media_user_id, request.form.get("username") or "")
            flash("portal_provider_profile_saved", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("portal_media_access"))

    @app.get("/portal/monitoring")
    @portal_login_required
    @permission_required("portal.monitoring.read_own")
    @portal_user_required
    def portal_monitoring():
        db = get_db(); ui = _require_feature(db, "monitoring")
        monitoring = load_portal_monitoring(db, int(g.auth_principal["vodum_user_id"]))
        return render_template("portal/monitoring.html", monitoring=monitoring, **ui, active_portal_page="monitoring")

    @app.get("/portal/support")
    @portal_login_required
    @permission_required("portal.support.read")
    @portal_user_required
    def portal_support():
        db = get_db(); ui = _require_feature(db, "support")
        user_id = int(g.auth_principal["vodum_user_id"])
        support = load_portal_support(db, user_id)
        if not support:
            return _portal_error("portal_account_missing")
        conversation = conversation_for_user(db, user_id) if support.get("quick_messages_enabled") else None
        all_messages = list_messages(db, conversation["id"]) if conversation and conversation.get("id") else []
        show_message_history = request.args.get("messages") == "all"
        has_older_messages = len(all_messages) > 6
        messages = all_messages if show_message_history else all_messages[-6:]
        if conversation and conversation.get("id"):
            mark_read(db, conversation["id"], "user")
        return render_template(
            "portal/support.html",
            support=support,
            conversation=conversation,
            messages=messages,
            has_older_messages=has_older_messages,
            show_message_history=show_message_history,
            **ui,
            active_portal_page="support",
        )

    @app.post("/portal/support/messages")
    @portal_login_required
    @permission_required("portal.support.read")
    @portal_user_required
    def portal_support_message_send():
        db = get_db(); _require_feature(db, "support")
        enabled = db.query_one("SELECT portal_quick_messages_enabled,contact_email,admin_email,brand_name FROM settings WHERE id=1") or {}
        enabled = dict(enabled)
        if not enabled.get("portal_quick_messages_enabled"):
            abort(404)
        conversation = conversation_for_user(db, int(g.auth_principal["vodum_user_id"]), create=True)
        try:
            add_message(db, conversation["id"], "user", request.form.get("body"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("portal_support"))
        recipient = (enabled.get("contact_email") or enabled.get("admin_email") or "").strip()
        if recipient:
            brand_name = str(enabled.get("brand_name") or "VODUM").strip()
            sender = conversation.get("username") or conversation.get("email") or "un utilisateur"
            send_email_via_settings(
                recipient,
                f"{brand_name} - nouveau message utilisateur",
                f"Un nouveau message de {sender} est disponible dans Communications > Inbox.",
            )
        flash("portal_message_sent", "success")
        return redirect(url_for("portal_support"))
