# Auto-split from app.py (keep URLs/endpoints intact)
import json

from flask import render_template, request, redirect, url_for, flash, jsonify

from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import auto_enable_stream_enforcer

from web.helpers import get_db, add_log
from .users_list import get_merge_suggestions
from api.subscriptions import update_user_expiration
from core.user_credentials import change_jellyfin_password
from core.usage_risk import build_usage_risk_for_user
from core.user_active_policies import load_active_policies_for_user
from core.user_notification_history import load_user_notification_history
from core.user_subscription_snapshots import (
    apply_template_snapshot,
    clear_template_snapshot,
)
from core.user_profile_context import (
    enrich_media_servers,
    load_expiration_lock,
    load_merged_usernames,
    load_referral_context,
    normalize_profile_date,
)
from core.user_plex_options import apply_user_plex_options, queue_user_plex_option_syncs
from core.user_referral_admin import update_user_referrer
from core.user_profile_form import normalize_user_profile_overrides
from core.user_detail_repository import (
    load_referral_admin_data,
    load_user_access_rows,
    load_user_detail,
    load_user_detail_settings,
    load_user_provider_types,
)


task_logger = get_logger("tasks_ui")
logger = get_logger("users_detail")

def register(app):
    @app.route("/users/<int:user_id>/change-jellyfin-password", methods=["POST"])
    def user_change_jellyfin_password(user_id):
        try:
            db = get_db()

            password = (
                request.form.get("jellyfin_new_password")
                or request.form.get("password")
                or ""
            ).strip()

            if not password:
                return {
                    "ok": False,
                    "error": "missing_password",
                }, 400

            selected_server_ids = {
                int(x)
                for x in request.form.getlist("server_ids")
                if str(x).isdigit()
            }

            return change_jellyfin_password(db, user_id, password, selected_server_ids)
        except Exception as e:

            logger.exception(
                f"[JELLYFIN PASSWORD] Fatal error for user_id={user_id}: {e}"
            )

            return jsonify({
                "ok": False,
                "error": str(e)
            }), 500


    @app.route("/users/<int:user_id>/save", methods=["POST"])
    def user_detail_save(user_id):
        db = get_db()

        user = load_user_detail(db, user_id)
        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        expiration_lock = load_expiration_lock(db, user_id)
        
        settings = load_user_detail_settings(db)

        try:
            user_notifications_can_override = int(settings.get("user_notifications_can_override") or 0) == 1
        except Exception:
            user_notifications_can_override = False

        allowed_types = load_user_provider_types(db, user_id)

        form = request.form

        # Champs texte classiques (vide ou espaces ? on garde l’ancienne valeur)
        username        = (form.get("username") or "").strip() or user.get("username")
        firstname       = (form.get("firstname") or "").strip() or user.get("firstname")
        lastname        = (form.get("lastname") or "").strip() or user.get("lastname")
        second_email    = (form.get("second_email") or "").strip() or user.get("second_email")
        raw_exp = (form.get("expiration_date") or "").strip()
        raw_ren = (form.get("renewal_date") or "").strip()

        # Keep existing values by default (do NOT wipe on parse failure)
        expiration_date = user.get("expiration_date")
        renewal_date = user.get("renewal_date")

        if expiration_lock["locked"]:
            expiration_date = user.get("expiration_date")
        elif raw_exp:
            parsed = normalize_profile_date(raw_exp)
            if parsed is not None:
                expiration_date = parsed
            else:
                flash("invalid_expiration_date_format", "error")

        if raw_ren:
            parsed = normalize_profile_date(raw_ren)
            if parsed is not None:
                renewal_date = parsed
            else:
                flash("invalid_renewal_date_format", "error")
        renewal_method  = (form.get("renewal_method") or "").strip() or user.get("renewal_method")

        subscription_template_id_raw = (form.get("subscription_template_id") or "").strip()
        if subscription_template_id_raw in ("", "none", "null"):
            requested_subscription_template_id = None
        elif subscription_template_id_raw.isdigit():
            requested_subscription_template_id = int(subscription_template_id_raw)
        else:
            flash("subscription_apply_invalid", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="general"))

        current_subscription_template_id = (
            int(user["subscription_template_id"])
            if user.get("subscription_template_id") is not None
            else None
        )

        if expiration_lock["locked"]:
            requested_subscription_template_id = current_subscription_template_id

        # Notes : on autorise le vide volontaire
        if "notes" in form:
            notes = (form.get("notes") or "").strip()
        else:
            notes = user.get("notes")

        # Discord : vide volontaire = NULL
        discord_user_id = (form.get("discord_user_id") or "").strip() or None
        discord_name    = (form.get("discord_name") or "").strip() or None

        referrer_user_id_raw = (form.get("referrer_user_id") or "").strip()
        requested_referrer_user_id = int(referrer_user_id_raw) if referrer_user_id_raw.isdigit() else None
        referral_settings, current_referral = load_referral_admin_data(db, user_id)

        selected_subscription_is_lifetime = False
        if requested_subscription_template_id is not None:
            selected_subscription = db.query_one(
                """
                SELECT is_lifetime
                FROM subscription_templates
                WHERE id = ?
                """,
                (requested_subscription_template_id,),
            )
            selected_subscription_is_lifetime = (
                int(selected_subscription["is_lifetime"] or 0) == 1
                if selected_subscription
                else False
            )

        overrides = normalize_user_profile_overrides(
            form,
            expiration_locked=expiration_lock["locked"],
            subscription_is_lifetime=selected_subscription_is_lifetime,
            current_expiration_override=user["expiration_date_override"],
            notifications_can_override=user_notifications_can_override,
        )
        expiration_date_override = overrides["expiration_date_override"]
        max_streams_override = overrides["max_streams_override"]
        notifications_order_override = overrides["notifications_order_override"]

        # --- MAJ infos Vodum ---
        db.execute(
            """
            UPDATE vodum_users
            SET username = ?,
                firstname = ?, lastname = ?, second_email = ?,
                renewal_date = ?, renewal_method = ?, notes = ?,
                max_streams_override = ?,
                expiration_date_override = ?,
                discord_user_id = ?, discord_name = ?, notifications_order_override = ?
            WHERE id = ?
            """,
            (
                username,
                firstname, lastname, second_email,
                renewal_date, renewal_method, notes,
                max_streams_override,
                expiration_date_override,
                discord_user_id, discord_name, notifications_order_override,
                user_id,
            ),
        )

        if requested_subscription_template_id != current_subscription_template_id:
            try:
                if requested_subscription_template_id is None:
                    clear_template_snapshot(db, user_id)
                    add_log(
                        "info",
                        "subscriptions",
                        f"Subscription removed from user #{user_id} via user_detail",
                    )
                else:
                    applied_name = apply_template_snapshot(
                        db,
                        user_id,
                        requested_subscription_template_id,
                        auto_enable_stream_enforcer,
                    )
                    add_log(
                        "info",
                        "subscriptions",
                        f"Template applied from user_detail to user #{user_id}: {applied_name} (template_id={requested_subscription_template_id})"
                    )
            except ValueError:
                flash("subscription_template_not_found", "error")
                return redirect(url_for("user_detail", user_id=user_id, tab="general"))

        referral_error = update_user_referrer(
            db,
            user_id=user_id,
            requested_referrer_user_id=requested_referrer_user_id,
            current_referral=current_referral,
            referral_settings=referral_settings,
        )
        if referral_error:
            flash(referral_error, "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="general"))

        # Gestion expiration (vodum_users.expiration_date est contractuel)
        if expiration_date != user.get("expiration_date"):
            update_user_expiration(
                user_id,
                expiration_date,
                reason="ui_manual",
                db=db,
            )

        plex_options_changed = apply_user_plex_options(
            db,
            user_id,
            form,
            debug_logger=task_logger if is_debug_mode_enabled() else None,
        )

        if plex_options_changed and "plex" in allowed_types:
            queue_user_plex_option_syncs(db, user_id, task_logger=task_logger)

        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id))

    @app.route("/users/<int:user_id>", methods=["GET"])
    def user_detail(user_id):
        db = get_db()
        sent_emails = []
        sent_discord = []


        # --------------------------------------------------
        # Charger l’utilisateur (VODUM)
        # --------------------------------------------------
        user = load_user_detail(db, user_id)

        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        # on convertit en dict pour éviter les surprises sqlite3.Row
        tab = (request.args.get("tab") or "general").strip().lower()
        if tab not in ("general", "monitoring", "access", "notifications", "media"):
            tab = "general"

        mview = (request.args.get("view") or "profile").strip().lower()
        if mview not in ("profile", "history", "ip"):
            mview = "profile"

        # --------------------------------------------------
        # Never used: no playback/session history linked to this VODUM user
        # --------------------------------------------------
        never_used = not db.query_one(
            """
            SELECT 1
            FROM media_session_history msh
            JOIN media_users mu ON mu.id = msh.media_user_id
            WHERE mu.vodum_user_id = ?
            LIMIT 1
            """,
            (user_id,),
        ) if tab == "general" else False

        # --------------------------------------------------
        # Subscription template (optional)
        # --------------------------------------------------
        subscription_template = None
        try:
            if user.get("subscription_template_id") is not None:
                subscription_template = db.query_one(
                    "SELECT id, name FROM subscription_templates WHERE id=?",
                    (int(user["subscription_template_id"]),),
                )
        except Exception:
            subscription_template = None

        user["subscription_template_name"] = subscription_template["name"] if subscription_template else None

        subscription_templates = db.query(
            """
            SELECT id, name, is_lifetime
            FROM subscription_templates
            WHERE is_enabled = 1
            ORDER BY name ASC
            """
        ) or [] if tab == "general" else []

        # --------------------------------------------------
        # Settings (needed for per-user notification override)
        # --------------------------------------------------
        settings = load_user_detail_settings(db) if tab in ("general", "access") else {}

        try:
            user_notifications_can_override = int(settings.get("user_notifications_can_override") or 0) == 1
        except Exception:
            user_notifications_can_override = False


        # --------------------------------------------------
        # Types de serveurs réellement liés à l'utilisateur
        # (basé sur media_users + servers)
        # --------------------------------------------------
        allowed_types = (
            load_user_provider_types(db, user_id)
            if tab in ("general", "access", "media")
            else []
        )

        # --------------------------------------------------
        # Monitoring: on a besoin d'un media_users.id pour ouvrir la page monitoring/user/<id>
        # (on prend le premier media_user lié au vodum_user)
        # --------------------------------------------------
        monitoring_mu = db.query_one(
            "SELECT id FROM media_users WHERE vodum_user_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        ) if tab == "monitoring" else None
        monitoring_mu_id = int(monitoring_mu["id"]) if (monitoring_mu and monitoring_mu["id"] is not None) else None





        # ==================================================
        # GET ? Chargement infos complètes
        # ==================================================

        servers, libraries = load_user_access_rows(
            db,
            user_id,
            include_servers=tab in ("general", "access", "media"),
            include_libraries=tab == "access",
        )
        servers = enrich_media_servers(servers)
        active_user_policies = load_active_policies_for_user(db, user_id) if tab == "general" else []



        merge_suggestions = get_merge_suggestions(db, user_id, limit=None) if tab == "access" else []

        # --------------------------------------------------
        # merged_usernames = tous les usernames (media_users) liés à ce vodum_user_id
        # (qu'ils soient "merge" ou le compte principal)
        # SAUF le username identique à celui affiché (vodum_users.username)
        # --------------------------------------------------
        merged_usernames = (
            load_merged_usernames(db, user_id, user.get("username") or "")
            if tab == "general"
            else []
        )

        # ----------------------------
        # Notification history paging
        # ----------------------------
        notification_history = load_user_notification_history(
            db,
            user_id,
            request.args.get("email_page"),
            request.args.get("discord_page"),
            enabled=tab == "notifications",
        )
        sent_emails = notification_history["sent_emails"]
        sent_discord = notification_history["sent_discord"]
        email_page = notification_history["email_page"]
        email_pages = notification_history["email_pages"]
        email_total = notification_history["email_total"]
        discord_page = notification_history["discord_page"]
        discord_pages = notification_history["discord_pages"]
        discord_total = notification_history["discord_total"]
        per_page = notification_history["per_page"]

        referral_context = (
            load_referral_context(db, user_id, user.get("referrer_user_id"))
            if tab == "general"
            else {
                "referral": None,
                "referrer_fallback": None,
                "referral_stats": {
                    "total_referrals": 0,
                    "pending_referrals": 0,
                    "qualified_referrals": 0,
                    "rewarded_referrals": 0,
                },
                "referred_users": [],
            }
        )
        referral = referral_context["referral"]
        referrer_fallback = referral_context["referrer_fallback"]
        referral_stats = referral_context["referral_stats"]
        referred_users = referral_context["referred_users"]

        usage_risk = build_usage_risk_for_user(db, user_id) if tab == "general" else {}
        expiration_lock = load_expiration_lock(db, user_id) if tab == "general" else None
        
        return render_template(
            "users/user_detail.html",
            user=user,
            subscription_templates=subscription_templates,
            never_used=never_used,
            servers=servers,
            libraries=libraries,
            sent_emails=sent_emails,
            sent_discord=sent_discord,
            allowed_types=allowed_types,
            expiration_lock=expiration_lock,
            merge_suggestions=merge_suggestions,
            user_servers=servers,
            active_user_policies=active_user_policies,
            usage_risk=usage_risk,
            merged_usernames=merged_usernames,
            email_page=email_page,
            email_pages=email_pages,
            email_total=email_total,

            discord_page=discord_page,
            discord_pages=discord_pages,
            discord_total=discord_total,

            per_page=per_page,


            # tabs
            tab=tab,
            mview=mview,
            monitoring_mu_id=monitoring_mu_id,
            settings=settings,
            user_notifications_can_override=user_notifications_can_override,
            
            referral=referral,
            referrer_fallback=referrer_fallback,
            referral_stats=referral_stats,
            referred_users=referred_users,
        )


