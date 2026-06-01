# Auto-split from app.py (keep URLs/endpoints intact)
import json
import re
import math
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, jsonify

from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import enable_and_run_task_by_name, auto_enable_stream_enforcer

from web.helpers import get_db, add_log
from .users_list import get_merge_suggestions
from .users_actions import _get_preferred_plex_media_user_id
from core.media_jobs import insert_plex_media_job
from api.subscriptions import update_user_expiration
from notifications_utils import parse_notifications_order
from core.providers.jellyfin_users import jellyfin_set_password


task_logger = get_logger("tasks_ui")
logger = get_logger("users_detail")

def _iso_date_or_none(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except Exception:
            pass

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", raw)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        try:
            return datetime.strptime(f"{y}-{mo}-{d}", "%Y-%m-%d").date().isoformat()
        except Exception:
            return None

    try:
        date_part = raw.split("T", 1)[0].split(" ", 1)[0]
        return datetime.fromisoformat(date_part).date().isoformat()
    except Exception:
        return None

def _parse_json_list(raw: str):
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _delete_locked_subscription_policies(db, vodum_user_id: int):
    rows = db.query(
        "SELECT id, rule_value_json FROM stream_policies WHERE scope_type='user' AND scope_id=?",
        (vodum_user_id,),
    ) or []
    for r in rows:
        try:
            rj = json.loads(r["rule_value_json"] or "{}")
        except Exception:
            rj = {}
        if rj.get("locked") and rj.get("subscription_name"):
            db.execute("DELETE FROM stream_policies WHERE id=?", (int(r["id"]),))


def _clear_template_snapshot(db, vodum_user_id: int):
    _delete_locked_subscription_policies(db, vodum_user_id)
    db.execute(
        "UPDATE vodum_users SET subscription_template_id=NULL WHERE id=?",
        (vodum_user_id,),
    )


def _apply_template_snapshot(db, vodum_user_id: int, template_id: int):
    tpl = db.query_one("SELECT id, name, policies_json FROM subscription_templates WHERE id=?", (template_id,))
    if not tpl:
        raise ValueError("subscription_template_not_found")

    tpl = dict(tpl)
    tname = tpl.get("name") or ""
    policies = _parse_json_list(tpl.get("policies_json") or "[]")

    _delete_locked_subscription_policies(db, vodum_user_id)

    any_enabled = False

    for p in policies:
        if not isinstance(p, dict):
            continue
        rule_type = (p.get("rule_type") or "").strip()
        if not rule_type:
            continue

        rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
        rule = dict(rule)
        rule["locked"] = True
        rule["subscription_name"] = tname

        provider = (p.get("provider") or "").strip() or None
        server_id = int(p["server_id"]) if str(p.get("server_id", "")).isdigit() else None
        is_enabled = 1 if str(p.get("is_enabled", "1")) == "1" else 0
        if is_enabled == 1:
            any_enabled = True
        priority = int(p.get("priority") or 100)

        db.execute(
            """
            INSERT INTO stream_policies(scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, rule_value_json)
            VALUES ('user', ?, ?, ?, ?, ?, ?, ?)
            """,
            (vodum_user_id, provider, server_id, is_enabled, priority, rule_type, json.dumps(rule)),
        )

    db.execute("UPDATE vodum_users SET subscription_template_id=? WHERE id=?", (template_id, vodum_user_id))

    if any_enabled:
        auto_enable_stream_enforcer()

    return tname

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

            jellyfin_accounts = db.query(
                """
                SELECT
                    mu.id,
                    mu.server_id,
                    mu.external_user_id,
                    mu.username,

                    s.name AS server_name,
                    s.url,
                    s.local_url,
                    s.public_url,
                    s.token AS token

                FROM media_users mu
                JOIN servers s ON s.id = mu.server_id

                WHERE mu.vodum_user_id = ?
                  AND mu.type = 'jellyfin'
                  AND s.type = 'jellyfin'
                """,
                (user_id,),
            ) or []

            # Filter selected servers
            if selected_server_ids:
                jellyfin_accounts = [
                    x for x in jellyfin_accounts
                    if int(x["server_id"]) in selected_server_ids
                ]

            updated = 0
            errors = []

            for account in jellyfin_accounts:

                try:

                    # THIS is what sends the password to Jellyfin
                    jellyfin_set_password(
                        dict(account),
                        str(account["external_user_id"]),
                        password,
                    )

                    # Store password locally
                    db.execute(
                        """
                        UPDATE media_users
                        SET stored_password = ?
                        WHERE id = ?
                        """,
                        (
                            password,
                            account["id"],
                        ),
                    )

                    updated += 1

                    task_logger.info(
                        f"[JELLYFIN PASSWORD] Updated password | "
                        f"vodum_user_id={user_id} | "
                        f"server_id={account['server_id']} | "
                        f"username={account['username']}"
                    )

                except Exception as e:

                    errors.append(
                        f"{account['server_name']}: {e}"
                    )

                    task_logger.error(
                        f"[JELLYFIN PASSWORD] Failed | "
                        f"vodum_user_id={user_id} | "
                        f"server_id={account['server_id']} | "
                        f"username={account['username']} | "
                        f"error={e}"
                    )

            return {
                "ok": len(errors) == 0,
                "updated": updated,
                "errors": errors,
            }
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

        user = db.query_one(
            "SELECT * FROM vodum_users WHERE id = ?",
            (user_id,),
        )
        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        user = dict(user)

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        try:
            user_notifications_can_override = int(settings.get("user_notifications_can_override") or 0) == 1
        except Exception:
            user_notifications_can_override = False

        allowed_types = [
            row["type"]
            for row in db.query(
                """
                SELECT DISTINCT s.type
                FROM servers s
                JOIN media_users mu ON mu.server_id = s.id
                WHERE mu.vodum_user_id = ?
                """,
                (user_id,),
            )
            if row["type"]
        ]

        form = request.form

        # Champs texte classiques (vide ou espaces → on garde l’ancienne valeur)
        username        = (form.get("username") or "").strip() or user.get("username")
        firstname       = (form.get("firstname") or "").strip() or user.get("firstname")
        lastname        = (form.get("lastname") or "").strip() or user.get("lastname")
        second_email    = (form.get("second_email") or "").strip() or user.get("second_email")
        raw_exp = (form.get("expiration_date") or "").strip()
        raw_ren = (form.get("renewal_date") or "").strip()

        # Keep existing values by default (do NOT wipe on parse failure)
        expiration_date = user.get("expiration_date")
        renewal_date = user.get("renewal_date")

        if raw_exp:
            parsed = _iso_date_or_none(raw_exp)
            if parsed is not None:
                expiration_date = parsed
            else:
                flash("invalid_expiration_date_format", "error")

        if raw_ren:
            parsed = _iso_date_or_none(raw_ren)
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

        # Notes : on autorise le vide volontaire
        if "notes" in form:
            notes = (form.get("notes") or "").strip()
        else:
            notes = user.get("notes")

        # Discord : vide volontaire = NULL
        discord_user_id = (form.get("discord_user_id") or "").strip() or None
        discord_name    = (form.get("discord_name") or "").strip() or None

        referral_settings = db.query_one("SELECT * FROM user_referral_settings WHERE id = 1")
        referral_settings = dict(referral_settings) if referral_settings else {}

        referrer_user_id_raw = (form.get("referrer_user_id") or "").strip()
        requested_referrer_user_id = int(referrer_user_id_raw) if referrer_user_id_raw.isdigit() else None

        current_referral = db.query_one(
            "SELECT * FROM user_referrals WHERE referred_user_id = ? LIMIT 1",
            (user_id,),
        )
        current_referral = dict(current_referral) if current_referral else None

        # Optional per-user override
        # Empty or 0 => NULL (no override, policy applies)
        expiration_date_override = 1 if form.get("expiration_date_override") == "1" else 0
        raw_override = form.get("max_streams_override")
        max_streams_override = None
        if raw_override is not None:
            raw_override = raw_override.strip()
            if raw_override != "":
                try:
                    parsed_override = int(raw_override)
                    max_streams_override = parsed_override if parsed_override > 0 else None
                except Exception:
                    max_streams_override = None

        # --------------------------------------------------
        # Per-user notification order override (optional)
        # - Only allowed if enabled globally in settings
        # --------------------------------------------------
        notifications_order_override = None
        if user_notifications_can_override:
            use_global = (form.get("use_global_notifications_order") == "1")
            if not use_global:
                raw = (form.get("user_notifications_order") or "").strip()
                if raw:
                    notifications_order_override = ",".join(parse_notifications_order(raw))
                else:
                    notifications_order_override = None

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
                    _clear_template_snapshot(db, user_id)
                    add_log(
                        "info",
                        "subscriptions",
                        f"Subscription removed from user #{user_id} via user_detail",
                    )
                else:
                    applied_name = _apply_template_snapshot(db, user_id, requested_subscription_template_id)
                    add_log(
                        "info",
                        "subscriptions",
                        f"Template applied from user_detail to user #{user_id}: {applied_name} (template_id={requested_subscription_template_id})"
                    )
            except ValueError:
                flash("subscription_template_not_found", "error")
                return redirect(url_for("user_detail", user_id=user_id, tab="general"))

        current_referrer_user_id = int(current_referral["referrer_user_id"]) if current_referral and current_referral.get("referrer_user_id") else None

        if requested_referrer_user_id == user_id:
            flash("Referrer cannot be the same user", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="general"))

        if requested_referrer_user_id != current_referrer_user_id:
            if current_referral and current_referral.get("status") in ("qualified", "rewarded"):
                flash("Referrer cannot be changed after qualification/reward", "error")
                return redirect(url_for("user_detail", user_id=user_id, tab="general"))

            if current_referral and int(referral_settings.get("allow_referrer_change_before_qualification") or 0) != 1:
                flash("Referrer change is disabled", "error")
                return redirect(url_for("user_detail", user_id=user_id, tab="general"))

            if requested_referrer_user_id is None:
                db.execute("UPDATE vodum_users SET referrer_user_id = NULL WHERE id = ?", (user_id,))
                if current_referral:
                    db.execute(
                        """
                        UPDATE user_referrals
                        SET status = 'cancelled',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (int(current_referral["id"]),),
                    )
                    db.execute(
                        """
                        INSERT INTO user_referral_events(
                            referral_id, event_type, actor,
                            old_referrer_user_id, new_referrer_user_id, details_json
                        )
                        VALUES (?, 'cancelled', 'ui', ?, NULL, ?)
                        """,
                        (
                            int(current_referral["id"]),
                            current_referrer_user_id,
                            json.dumps({"source": "user_detail"}, ensure_ascii=False),
                        ),
                    )
            else:
                referrer = db.query_one(
                    "SELECT id, status FROM vodum_users WHERE id = ?",
                    (requested_referrer_user_id,),
                )
                if not referrer:
                    flash("Referrer not found", "error")
                    return redirect(url_for("user_detail", user_id=user_id, tab="general"))

                if (referrer["status"] or "").lower() != "active":
                    flash("Referrer must be active", "error")
                    return redirect(url_for("user_detail", user_id=user_id, tab="general"))

                db.execute(
                    "UPDATE vodum_users SET referrer_user_id = ? WHERE id = ?",
                    (requested_referrer_user_id, user_id),
                )

                qualification_days = int(referral_settings.get("qualification_days") or 60)
                reward_days = int(referral_settings.get("reward_days") or 60)

                if current_referral:
                    db.execute(
                        """
                        UPDATE user_referrals
                        SET referrer_user_id = ?,
                            status = 'pending',
                            start_at = CURRENT_TIMESTAMP,
                            qualification_due_at = datetime('now', ?),
                            qualified_at = NULL,
                            reward_granted_at = NULL,
                            reward_expiration_before = NULL,
                            reward_expiration_after = NULL,
                            notification_sent_at = NULL,
                            last_error = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            requested_referrer_user_id,
                            f"+{qualification_days} days",
                            int(current_referral["id"]),
                        ),
                    )
                    db.execute(
                        """
                        INSERT INTO user_referral_events(
                            referral_id, event_type, actor,
                            old_referrer_user_id, new_referrer_user_id, details_json
                        )
                        VALUES (?, 'referrer_changed', 'ui', ?, ?, ?)
                        """,
                        (
                            int(current_referral["id"]),
                            current_referrer_user_id,
                            requested_referrer_user_id,
                            json.dumps({"source": "user_detail"}, ensure_ascii=False),
                        ),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO user_referrals(
                            referrer_user_id,
                            referred_user_id,
                            status,
                            referral_source,
                            start_at,
                            qualification_due_at,
                            qualification_days_snapshot,
                            reward_days_snapshot,
                            created_at,
                            updated_at
                        )
                        VALUES(
                            ?, ?, 'pending', 'manual',
                            CURRENT_TIMESTAMP,
                            datetime('now', ?),
                            ?, ?,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            requested_referrer_user_id,
                            user_id,
                            f"+{qualification_days} days",
                            qualification_days,
                            reward_days,
                        ),
                    )

        # Gestion expiration (vodum_users.expiration_date est contractuel)
        if expiration_date != user.get("expiration_date"):
            update_user_expiration(
                user_id,
                expiration_date,
                reason="ui_manual",
                db=db,
            )

        # ------------------------------------------------------------------
        # Helper pour répliquer les flags Plex sur serveurs même owner
        # ------------------------------------------------------------------
        def replicate_plex_flags_same_owner(db, vodum_user_id: int, changed_mu_id: int, plex_share_new: dict):
            """
            Réplique allowSync/allowCameraUpload/allowChannels + filtres sur tous les serveurs Plex
            qui partagent le même owner (approché par même servers.token).
            """
            row = db.query_one("SELECT server_id FROM media_users WHERE id = ?", (changed_mu_id,))
            if not row:
                return
            changed_server_id = int(row["server_id"])

            srv = db.query_one("SELECT token FROM servers WHERE id = ?", (changed_server_id,))
            if not srv:
                return
            srv = dict(srv)
            owner_token = srv.get("token")
            if not owner_token:
                return

            owner_servers = db.query(
                "SELECT id FROM servers WHERE type='plex' AND token = ?",
                (owner_token,),
            )
            owner_server_ids = [int(s["id"]) for s in owner_servers]
            if not owner_server_ids:
                return

            placeholders = ",".join(["?"] * len(owner_server_ids))

            rows = db.query(
                f"""
                SELECT mu.id, mu.details_json
                FROM media_users mu
                JOIN servers s ON s.id = mu.server_id
                WHERE mu.vodum_user_id = ?
                  AND s.type = 'plex'
                  AND mu.type = 'plex'
                  AND mu.server_id IN ({placeholders})
                """,
                (vodum_user_id, *owner_server_ids),
            )

            for r in rows:
                mu_id2 = int(r["id"])
                try:
                    details2 = json.loads(r["details_json"] or "{}")
                except Exception:
                    details2 = {}

                if not isinstance(details2, dict):
                    details2 = {}

                plex_share2 = details2.get("plex_share", {})
                if not isinstance(plex_share2, dict):
                    plex_share2 = {}

                for k in ("allowSync", "allowCameraUpload", "allowChannels", "filterMovies", "filterTelevision", "filterMusic"):
                    if k in plex_share_new:
                        plex_share2[k] = plex_share_new[k]

                details2["plex_share"] = plex_share2

                db.execute(
                    "UPDATE media_users SET details_json = ? WHERE id = ?",
                    (json.dumps(details2, ensure_ascii=False), mu_id2),
                )

        plex_options_changed = False

        plex_media = db.query(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.vodum_user_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (user_id,),
        )

        truthy = {"1", "true", "on", "yes"}

        for mu in plex_media:
            mu_id = int(mu["id"])

            try:
                details = json.loads(mu["details_json"] or "{}")
            except Exception:
                details = {}

            if not isinstance(details, dict):
                details = {}

            plex_share = details.get("plex_share", {})
            if not isinstance(plex_share, dict):
                plex_share = {}

            old_plex_share = dict(plex_share)

            vals = form.getlist(f"allow_sync_{mu_id}")
            if is_debug_mode_enabled():
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_sync getlist={vals}")
            v = vals[-1] if vals else None
            if v is not None:
                plex_share["allowSync"] = 1 if str(v).strip().lower() in truthy else 0
            else:
                plex_share["allowSync"] = int(plex_share.get("allowSync", 0) or 0)

            vals = form.getlist(f"allow_camera_upload_{mu_id}")
            if is_debug_mode_enabled():
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_camera_upload getlist={vals}")
            v = vals[-1] if vals else None
            if v is not None:
                plex_share["allowCameraUpload"] = 1 if str(v).strip().lower() in truthy else 0
            else:
                plex_share["allowCameraUpload"] = int(plex_share.get("allowCameraUpload", 0) or 0)

            vals = form.getlist(f"allow_channels_{mu_id}")
            if is_debug_mode_enabled():
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_channels getlist={vals}")
            v = vals[-1] if vals else None
            if v is not None:
                plex_share["allowChannels"] = 1 if str(v).strip().lower() in truthy else 0
            else:
                plex_share["allowChannels"] = int(plex_share.get("allowChannels", 0) or 0)

            plex_share["filterMovies"] = (form.get(f"filter_movies_{mu_id}") or "").strip()
            plex_share["filterTelevision"] = (form.get(f"filter_television_{mu_id}") or "").strip()
            plex_share["filterMusic"] = (form.get(f"filter_music_{mu_id}") or "").strip()

            details["plex_share"] = plex_share

            if old_plex_share != plex_share:
                plex_options_changed = True

                db.execute(
                    "UPDATE media_users SET details_json = ? WHERE id = ?",
                    (json.dumps(details, ensure_ascii=False), mu_id),
                )

                replicate_plex_flags_same_owner(
                    db,
                    vodum_user_id=user_id,
                    changed_mu_id=mu_id,
                    plex_share_new=plex_share,
                )

        if plex_options_changed and "plex" in allowed_types:
            plex_media_for_jobs = db.query(
                """
                SELECT mu.id, mu.server_id
                FROM media_users mu
                JOIN servers s ON s.id = mu.server_id
                WHERE mu.vodum_user_id = ?
                  AND s.type = 'plex'
                  AND mu.type = 'plex'
                """,
                (user_id,),
            )

            plex_server_ids = sorted({int(mu["server_id"]) for mu in plex_media_for_jobs if mu["server_id"] is not None})

            for server_id in plex_server_ids:
                preferred_media_user_id = _get_preferred_plex_media_user_id(
                    db,
                    user_id,
                    server_id,
                )

                dedupe_key = f"plex:sync:server={server_id}:vodum_user={user_id}:user_detail_save"

                payload = {
                    "reason": "user_detail_save",
                    "updated_options": True,
                    "preferred_media_user_id": preferred_media_user_id,
                }

                inserted = insert_plex_media_job(
                    db,
                    action="sync",
                    vodum_user_id=user_id,
                    server_id=server_id,
                    library_id=None,
                    dedupe_key=dedupe_key,
                    payload=payload,
                )

                if inserted:
                    task_logger.info(
                        f"[MEDIA JOB CREATED] provider=plex action=sync "
                        f"user_id={user_id} server_id={server_id} "
                        f"preferred_media_user_id={preferred_media_user_id} reason=user_detail_save"
                    )

            try:
                enable_and_run_task_by_name("apply_plex_access_updates")
            except Exception:
                pass

        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id))

    def _load_active_policies_for_user(db, vodum_user_id: int):
        media_rows = db.query(
            """
            SELECT
                mu.server_id,
                LOWER(COALESCE(s.type, mu.type, '')) AS provider,
                COALESCE(s.name, '') AS server_name
            FROM media_users mu
            LEFT JOIN servers s ON s.id = mu.server_id
            WHERE mu.vodum_user_id = ?
            """,
            (vodum_user_id,),
        ) or []

        server_ids = []
        providers = set()
        server_names = {}

        for row in media_rows:
            r = dict(row)
            if r.get("server_id") is not None:
                sid = int(r["server_id"])
                server_ids.append(sid)
                server_names[sid] = r.get("server_name") or f"#{sid}"

            provider = (r.get("provider") or "").strip().lower()
            if provider:
                providers.add(provider)

        clauses = ["p.scope_type = 'global'", "(p.scope_type = 'user' AND p.scope_id = ?)"]
        params = [vodum_user_id]

        if server_ids:
            placeholders = ",".join("?" for _ in server_ids)
            clauses.append(f"(p.scope_type = 'server' AND p.scope_id IN ({placeholders}))")
            params.extend(server_ids)

            clauses.append(f"(p.server_id IN ({placeholders}))")
            params.extend(server_ids)

        rows = db.query(
            f"""
            SELECT
                p.*,
                s.name AS policy_server_name
            FROM stream_policies p
            LEFT JOIN servers s ON s.id = p.server_id
            WHERE p.is_enabled = 1
              AND ({' OR '.join(clauses)})
            ORDER BY p.priority ASC, p.id ASC
            """,
            tuple(params),
        ) or []

        policies = []

        for row in rows:
            p = dict(row)

            provider = (p.get("provider") or "").strip().lower()
            if provider and providers and provider not in providers:
                continue

            try:
                rule = json.loads(p.get("rule_value_json") or "{}")
                if not isinstance(rule, dict):
                    rule = {}
            except Exception:
                rule = {}

            scope_type = (p.get("scope_type") or "").strip()
            scope_label = scope_type

            if scope_type == "global":
                scope_label = "Global"
            elif scope_type == "user":
                scope_label = "User"
            elif scope_type == "server":
                sid = p.get("scope_id")
                scope_label = server_names.get(int(sid), f"Server #{sid}") if sid is not None else "Server"

            origin_type = "Manual"
            origin_label = "Manual"

            system_tag = (rule.get("system_tag") or "").strip()
            subscription_name = (rule.get("subscription_name") or "").strip()

            if system_tag == "expired_subscription":
                origin_type = "System"
                origin_label = "Expired subscription"
            elif subscription_name:
                origin_type = "Subscription"
                origin_label = subscription_name

            value_parts = []

            if "max" in rule:
                value_parts.append(f"max={rule.get('max')}")
            elif p.get("rule_type") == "max_bitrate_kbps" and rule.get("kbps") is not None:
                value_parts.append(f"kbps={rule.get('kbps')}")
            elif p.get("rule_type") == "device_allowlist":
                devices = rule.get("devices") or rule.get("allowed_devices") or []
                if isinstance(devices, list):
                    value_parts.append(", ".join(str(x) for x in devices) if devices else "empty")
                else:
                    value_parts.append(str(devices))
            elif p.get("rule_type") == "ban_4k_transcode":
                value_parts.append("enabled")
            else:
                value_parts.append("configured")

            selector = rule.get("selector")
            if selector:
                value_parts.append(f"selector={selector}")

            if rule.get("allow_local_ip") or rule.get("local_ip"):
                value_parts.append("local_ip=yes")

            policies.append({
                "id": p.get("id"),
                "rule_type": p.get("rule_type"),
                "scope_type": scope_type,
                "scope_label": scope_label,
                "origin_type": origin_type,
                "origin_label": origin_label,
                "provider": provider or "both",
                "priority": p.get("priority"),
                "value": " | ".join(value_parts),
            })

        return policies

    @app.route("/users/<int:user_id>", methods=["GET"])
    def user_detail(user_id):
        db = get_db()
        sent_emails = []
        sent_discord = []


        # --------------------------------------------------
        # Charger l’utilisateur (VODUM)
        # --------------------------------------------------
        user = db.query_one(
            "SELECT * FROM vodum_users WHERE id = ?",
            (user_id,),
        )

        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        # on convertit en dict pour éviter les surprises sqlite3.Row
        user = dict(user)

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
        )

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
            "SELECT id, name FROM subscription_templates ORDER BY name ASC"
        ) or []

        # --------------------------------------------------
        # Settings (needed for per-user notification override)
        # --------------------------------------------------
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        try:
            user_notifications_can_override = int(settings.get("user_notifications_can_override") or 0) == 1
        except Exception:
            user_notifications_can_override = False


        # --------------------------------------------------
        # Types de serveurs réellement liés à l'utilisateur
        # (basé sur media_users + servers)
        # --------------------------------------------------
        allowed_types = [
            row["type"]
            for row in db.query(
                """
                SELECT DISTINCT s.type
                FROM servers s
                JOIN media_users mu ON mu.server_id = s.id
                WHERE mu.vodum_user_id = ?
                """,
                (user_id,),
            )
            if row["type"]
        ]

        # --------------------------------------------------
        # Tabs (User detail)
        # --------------------------------------------------
        tab = (request.args.get("tab") or "general").strip().lower()
        if tab not in ("general", "monitoring", "access", "notifications", "media"):
            tab = "general"

        mview = (request.args.get("view") or "profile").strip().lower()
        if mview not in ("profile", "history", "ip"):
            mview = "profile"

        # --------------------------------------------------
        # Monitoring: on a besoin d'un media_users.id pour ouvrir la page monitoring/user/<id>
        # (on prend le premier media_user lié au vodum_user)
        # --------------------------------------------------
        monitoring_mu = db.query_one(
            "SELECT id FROM media_users WHERE vodum_user_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        )
        monitoring_mu_id = int(monitoring_mu["id"]) if (monitoring_mu and monitoring_mu["id"] is not None) else None





        # ==================================================
        # GET → Chargement infos complètes
        # ==================================================

        servers = db.query(
            """
            SELECT
                s.*,
                s.id AS server_id,

                mu.id AS media_user_id,
                mu.external_user_id,
                mu.username AS media_username,
                mu.email AS media_email,
                mu.avatar AS media_avatar,
                mu.type AS media_type,
                mu.role AS media_role,
                mu.joined_at,
                mu.accepted_at,
                mu.raw_json,
                mu.details_json,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM media_user_libraries mul
                        WHERE mul.media_user_id = mu.id
                        LIMIT 1
                    ) THEN 1
                    ELSE 0
                END AS has_access
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.vodum_user_id = ?
              AND mu.id = (
                    SELECT mu2.id
                    FROM media_users mu2
                    WHERE mu2.vodum_user_id = mu.vodum_user_id
                      AND mu2.server_id = mu.server_id
                    ORDER BY
                        CASE
                            WHEN COALESCE(NULLIF(TRIM(mu2.details_json), ''), '') <> '' THEN 0
                            ELSE 1
                        END,
                        CASE
                            WHEN COALESCE(NULLIF(TRIM(mu2.raw_json), ''), '') <> '' THEN 0
                            ELSE 1
                        END,
                        mu2.id ASC
                    LIMIT 1
              )
            ORDER BY s.type, s.name
            """,
            (user_id,),
        )

        enriched = []
        for row in servers:
            r = dict(row)

            # defaults pour le template
            r["allow_sync"] = 0
            r["allow_camera_upload"] = 0
            r["allow_channels"] = 0
            r["filter_movies"] = ""
            r["filter_television"] = ""
            r["filter_music"] = ""

            try:
                details = json.loads(r.get("details_json") or "{}")
            except Exception:
                details = {}

            if not isinstance(details, dict):
                details = {}

            # Plex
            if r.get("media_type") == "plex":
                plex_share = details.get("plex_share", {})
                if not isinstance(plex_share, dict):
                    plex_share = {}

                r["allow_sync"] = 1 if plex_share.get("allowSync") else 0
                r["allow_camera_upload"] = 1 if plex_share.get("allowCameraUpload") else 0
                r["allow_channels"] = 1 if plex_share.get("allowChannels") else 0
                r["filter_movies"] = plex_share.get("filterMovies") or ""
                r["filter_television"] = plex_share.get("filterTelevision") or ""
                r["filter_music"] = plex_share.get("filterMusic") or ""

            r["_details_obj"] = details
            enriched.append(r)

        servers = enriched
        active_user_policies = _load_active_policies_for_user(db, user_id)
        
        libraries = db.query(
            """
            SELECT
                l.*,
                s.name AS server_name,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM media_user_libraries mul
                        JOIN media_users mu ON mu.id = mul.media_user_id
                        WHERE mul.library_id = l.id
                          AND mu.vodum_user_id = ?
                          AND mu.server_id = l.server_id
                    ) THEN 1
                    ELSE 0
                END AS has_access
            FROM libraries l
            JOIN servers s ON s.id = l.server_id
            ORDER BY s.name, l.name
            """,
            (user_id,),
        )



        merge_suggestions = get_merge_suggestions(db, user_id, limit=None)

        # --------------------------------------------------
        # merged_usernames = tous les usernames (media_users) liés à ce vodum_user_id
        # (qu'ils soient "merge" ou le compte principal)
        # SAUF le username identique à celui affiché (vodum_users.username)
        # --------------------------------------------------
        main_username = (user.get("username") or "").strip()
        main_username_norm = main_username.lower() if main_username else ""

        # On dédoublonne en insensible à la casse, mais on garde une forme "propre" pour l'affichage
        merged_usernames_map = {}  # key: lower(username) -> value: username (original)

        rows = db.query(
            """
            SELECT DISTINCT username
            FROM media_users
            WHERE vodum_user_id = ?
              AND username IS NOT NULL
              AND TRIM(username) <> ''
            """,
            (user_id,),
        )

        for r in rows:
            uname = str(r["username"]).strip()
            if not uname:
                continue

            # Ne pas afficher le username media_user si c'est le même que celui affiché (vodum_users.username)
            if main_username_norm and uname.lower() == main_username_norm:
                continue

            key = uname.lower()
            if key not in merged_usernames_map:
                merged_usernames_map[key] = uname

        merged_usernames = sorted(merged_usernames_map.values(), key=lambda x: x.lower())

        # ----------------------------
        # Notification history paging
        # ----------------------------
        def _safe_int(v, default):
            try:
                return int(v)
            except Exception:
                return default

        def _history_order_sql(alias="h"):
            return f"""
                COALESCE(
                    CASE
                        WHEN typeof({alias}.sent_at) = 'integer' THEN {alias}.sent_at
                        WHEN typeof({alias}.sent_at) = 'text' AND {alias}.sent_at GLOB '[0-9]*' THEN CAST({alias}.sent_at AS INTEGER)
                        ELSE CAST(strftime('%s', {alias}.sent_at) AS INTEGER)
                    END,
                    0
                ) DESC,
                {alias}.id DESC
            """

        def _build_history_label(row_dict):
            meta = {}
            try:
                meta = json.loads(row_dict.get("meta_json") or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}

            kind = (row_dict.get("kind") or "").strip().lower()

            if kind == "campaign":
                return (row_dict.get("campaign_name") or "").strip() or "Campaign"

            # template
            return (
                (row_dict.get("template_key") or "").strip()
                or (row_dict.get("template_name") or "").strip()
                or (meta.get("template_key") or "").strip()
                or "Template"
            )

        per_page = 10

        email_page = max(1, _safe_int(request.args.get("email_page"), 1))
        discord_page = max(1, _safe_int(request.args.get("discord_page"), 1))

        email_total = db.query_one(
            """
            SELECT COUNT(*) AS c
            FROM comm_history h
            WHERE h.user_id = ?
              AND h.channel_used = 'email'
            """,
            (user_id,),
        )["c"] or 0

        discord_total = db.query_one(
            """
            SELECT COUNT(*) AS c
            FROM comm_history h
            WHERE h.user_id = ?
              AND h.channel_used = 'discord'
            """,
            (user_id,),
        )["c"] or 0

        email_pages = max(1, math.ceil(email_total / per_page)) if email_total else 1
        discord_pages = max(1, math.ceil(discord_total / per_page)) if discord_total else 1

        email_page = min(email_page, email_pages)
        discord_page = min(discord_page, discord_pages)

        email_offset = (email_page - 1) * per_page
        discord_offset = (discord_page - 1) * per_page

        sent_emails_rows = db.query(
            f"""
            SELECT
                h.*,
                ct.key AS template_key,
                ct.name AS template_name,
                cc.name AS campaign_name
            FROM comm_history h
            LEFT JOIN comm_templates ct ON ct.id = h.template_id
            LEFT JOIN comm_campaigns cc ON cc.id = h.campaign_id
            WHERE h.user_id = ?
              AND h.channel_used = 'email'
            ORDER BY {_history_order_sql("h")}
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, email_offset),
        ) or []

        sent_discord_rows = db.query(
            f"""
            SELECT
                h.*,
                ct.key AS template_key,
                ct.name AS template_name,
                cc.name AS campaign_name
            FROM comm_history h
            LEFT JOIN comm_templates ct ON ct.id = h.template_id
            LEFT JOIN comm_campaigns cc ON cc.id = h.campaign_id
            WHERE h.user_id = ?
              AND h.channel_used = 'discord'
            ORDER BY {_history_order_sql("h")}
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, discord_offset),
        ) or []

        sent_emails = []
        for row in sent_emails_rows:
            item = dict(row)
            item["label"] = _build_history_label(item)
            sent_emails.append(item)

        sent_discord = []
        for row in sent_discord_rows:
            item = dict(row)
            item["label"] = _build_history_label(item)
            sent_discord.append(item)

        referral = db.query_one(
            """
            SELECT
                r.*,
                referrer.username AS referrer_username,
                referrer.email AS referrer_email
            FROM user_referrals r
            LEFT JOIN vodum_users referrer ON referrer.id = r.referrer_user_id
            WHERE r.referred_user_id = ?
            LIMIT 1
            """,
            (user_id,),
        )
        referral = dict(referral) if referral else None

        referrer_fallback = None
        if not referral and user.get("referrer_user_id"):
            row = db.query_one(
                """
                SELECT id, username, email
                FROM vodum_users
                WHERE id = ?
                LIMIT 1
                """,
                (user["referrer_user_id"],),
            )
            referrer_fallback = dict(row) if row else None

        referral_stats = db.query_one(
            """
            SELECT
                COUNT(*) AS total_referrals,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_referrals,
                SUM(CASE WHEN status = 'qualified' THEN 1 ELSE 0 END) AS qualified_referrals,
                SUM(CASE WHEN status = 'rewarded' THEN 1 ELSE 0 END) AS rewarded_referrals
            FROM user_referrals
            WHERE referrer_user_id = ?
            """,
            (user_id,),
        )
        referral_stats = dict(referral_stats) if referral_stats else {
            "total_referrals": 0,
            "pending_referrals": 0,
            "qualified_referrals": 0,
            "rewarded_referrals": 0,
        }

        referred_users = db.query(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                u.status,
                r.status AS referral_status,
                r.qualification_due_at
            FROM user_referrals r
            JOIN vodum_users u ON u.id = r.referred_user_id
            WHERE r.referrer_user_id = ?
            ORDER BY u.username ASC
            """,
            (user_id,),
        ) or []
        referred_users = [dict(x) for x in referred_users]

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
            merge_suggestions=merge_suggestions,
            user_servers=servers,
            active_user_policies=active_user_policies,
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





