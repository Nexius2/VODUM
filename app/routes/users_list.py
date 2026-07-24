# Auto-split from app.py (keep URLs/endpoints intact)
import json

from flask import (
    render_template, request, redirect, url_for, flash,
    Response, make_response,
)

from logging_utils import get_logger

from web.helpers import get_db
from web.pagination import normalize_page, normalize_page_size, page_bounds
from core.referral_bulk import bulk_update_referrals, normalize_referral_ids
from core.user_merge import build_merge_preview, merge_vodum_users
from core.user_merge_suggestions import get_merge_suggestions

task_logger = get_logger("tasks_ui")
USER_LIST_COLUMNS = """
                    u.id,
                    u.username,
                    u.email,
                    u.status,
                    u.expiration_date
"""

USER_REFERRAL_SETTINGS_COLUMNS = """
            enabled,
            reward_enabled,
            qualification_days,
            reward_days,
            allow_referrer_change_before_qualification,
            auto_notify_reward,
            auto_expire_pending,
            auto_archive_rewarded,
            auto_archive_expired,
            rewarded_archive_days,
            expired_archive_days,
            eligible_statuses
"""

USER_MERGE_COLUMNS = """
    id,
    username,
    firstname,
    lastname,
    email,
    second_email,
    expiration_date,
    renewal_method,
    renewal_date,
    status,
    created_at,
    notes
"""

USER_REFERRAL_LIST_COLUMNS = """
                    r.id,
                    r.referrer_user_id,
                    r.referred_user_id,
                    r.status,
                    r.start_at,
                    r.qualification_due_at,
                    r.reward_days_snapshot
"""

def register(app):
    @app.route("/users", methods=["GET"])
    def users_list():
        archive_mode = "active"
        db = get_db()

        tab = (request.args.get("tab") or "users").strip().lower()
        if tab not in ("users", "referrals", "referral_settings"):
            tab = "users"



        # --------------------------------------------------
        # Common params
        # --------------------------------------------------
        search = " ".join(
            request.args.get("q", "").split()
        ).strip()
        page = normalize_page(request.args.get("page", 1, type=int))
        per_page = normalize_page_size(request.args.get("per_page", 20, type=int))
        offset = (page - 1) * per_page

        # --------------------------------------------------
        # Users tab preferences memory
        # - keep sort/order/status in persistent cookies
        # - do NOT keep search text
        # --------------------------------------------------
        if tab == "users":
            cookie_sort = (request.cookies.get("users_list_sort") or "expiration_date").strip()
            cookie_order = (request.cookies.get("users_list_order") or "asc").strip().lower()

            default_statuses = [
                "active",
                "pre_expired",
                "reminder",
                "expired",
                "invited",
                "unfriended",
                "suspended",
                "unknown",
            ]

            cookie_statuses_raw = request.cookies.get("users_list_statuses")
            if cookie_statuses_raw:
                try:
                    cookie_statuses = json.loads(cookie_statuses_raw)
                    if not isinstance(cookie_statuses, list):
                        cookie_statuses = default_statuses[:]
                except Exception:
                    cookie_statuses = default_statuses[:]
            else:
                cookie_statuses = default_statuses[:]

            status_none_requested = request.args.get("status_none") == "1"

            arg_statuses = request.args.getlist("status")
            selected_statuses = arg_statuses if "status" in request.args else cookie_statuses

            valid_statuses = {
                "active",
                "pre_expired",
                "reminder",
                "expired",
                "invited",
                "unfriended",
                "suspended",
                "unknown",
            }

            selected_statuses = [
                str(s).strip().lower()
                for s in selected_statuses
                if str(s).strip().lower() in valid_statuses
            ]

            if status_none_requested:
                selected_statuses = []
            elif not selected_statuses:
                selected_statuses = default_statuses[:]

            sort = (request.args.get("sort") or cookie_sort or "username").strip()
            order = (request.args.get("order") or cookie_order or "asc").strip().lower()

            if order not in ("asc", "desc"):
                order = "asc"
        else:
            status_none_requested = request.args.get("status_none") == "1"

            valid_referral_statuses = [
                "pending",
                "qualified",
                "rewarded",
                "cancelled",
                "expired",
                "archived",
            ]

            selected_statuses = [
                str(s).strip().lower()
                for s in request.args.getlist("status")
                if str(s).strip().lower() in valid_referral_statuses
            ]

            if status_none_requested:
                selected_statuses = []
            elif "status" not in request.args:
                selected_statuses = valid_referral_statuses[:]

            sort = (request.args.get("sort") or "username").strip()
            order = (request.args.get("order") or "asc").strip().lower()

            if order not in ("asc", "desc"):
                order = "asc"

        subscription_templates = db.query(
            """
            SELECT id, name, is_default
            FROM subscription_templates
            WHERE COALESCE(is_enabled, 1) = 1
            ORDER BY is_default DESC, name ASC
            """
        ) or [] if tab in ("users", "referral_settings") else []

        referral_settings = db.query_one(
            f"SELECT {USER_REFERRAL_SETTINGS_COLUMNS} FROM user_referral_settings WHERE id = 1"
        ) if tab == "referral_settings" else None
        referral_settings = dict(referral_settings) if referral_settings else {
            "enabled": 0,
            "reward_enabled": 1,
            "qualification_days": 60,
            "reward_days": 60,
            "allow_referrer_change_before_qualification": 1,
            "auto_notify_reward": 1,
            "auto_expire_pending": 1,
            "auto_archive_rewarded": 1,
            "auto_archive_expired": 1,
            "rewarded_archive_days": 90,
            "expired_archive_days": 30,
            "eligible_statuses": "active",
        }

        referral_stats = db.query_one(
            """
            SELECT
                COUNT(*) AS total_referrals,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_referrals,
                SUM(CASE WHEN status = 'qualified' THEN 1 ELSE 0 END) AS qualified_referrals,
                SUM(CASE WHEN status = 'rewarded' THEN 1 ELSE 0 END) AS rewarded_referrals,
                SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired_referrals,
                SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) AS archived_referrals,
                COALESCE(SUM(CASE
                    WHEN reward_granted_at IS NOT NULL THEN COALESCE(reward_days_snapshot, 0)
                    ELSE 0
                END), 0) AS granted_days
            FROM user_referrals
            """
        ) if tab == "referrals" else None
        referral_stats = dict(referral_stats) if referral_stats else {
            "total_referrals": 0,
            "pending_referrals": 0,
            "qualified_referrals": 0,
            "rewarded_referrals": 0,
            "expired_referrals": 0,
            "archived_referrals": 0,
            "granted_days": 0,
        }

        # --------------------------------------------------
        # TAB = USERS
        # --------------------------------------------------
        users = []
        referrals = []
        total_users = 0
        total_referrals = 0
        total_pages = 1

        if tab == "users":
            sort_map = {
                "username": "u.username",
                "email": "u.email",
                "status": "u.status",
                "subscription": "subscription_sort_label",
                "expiration_date": "u.expiration_date",
                "servers_count": "servers_count",
                "libraries_count": "libraries_count",
            }
            sort_column = sort_map.get(sort, "u.username")

            query = f"""
                SELECT
                    {USER_LIST_COLUMNS},
                    st.name AS subscription_name,
                    CASE
                        WHEN MAX(CASE WHEN LOWER(COALESCE(s.type, '')) = 'plex'
                                       AND LOWER(COALESCE(mu.role, '')) = 'owner'
                                      THEN 1 ELSE 0 END) = 1
                            THEN 'Owner'
                        WHEN MAX(CASE WHEN LOWER(COALESCE(s.type, '')) = 'jellyfin'
                                       AND (
                                            LOWER(COALESCE(mu.role, '')) = 'admin'
                                            OR COALESCE(mu.raw_json, '') LIKE '%"IsAdministrator":true%'
                                            OR COALESCE(mu.raw_json, '') LIKE '%"IsAdministrator": true%'
                                       )
                                      THEN 1 ELSE 0 END) = 1
                            THEN 'Admin'
                        ELSE NULL
                    END AS subscription_role_label,
                    COALESCE(
                        CASE
                            WHEN MAX(CASE WHEN LOWER(COALESCE(s.type, '')) = 'plex'
                                           AND LOWER(COALESCE(mu.role, '')) = 'owner'
                                          THEN 1 ELSE 0 END) = 1
                                THEN 'Owner'
                            WHEN MAX(CASE WHEN LOWER(COALESCE(s.type, '')) = 'jellyfin'
                                           AND (
                                                LOWER(COALESCE(mu.role, '')) = 'admin'
                                                OR COALESCE(mu.raw_json, '') LIKE '%"IsAdministrator":true%'
                                                OR COALESCE(mu.raw_json, '') LIKE '%"IsAdministrator": true%'
                                           )
                                          THEN 1 ELSE 0 END) = 1
                                THEN 'Admin'
                            ELSE NULL
                        END,
                        st.name
                    ) AS subscription_sort_label,
                    COUNT(DISTINCT mu.server_id) AS servers_count,
                    COUNT(DISTINCT mul.library_id) AS libraries_count
                                    FROM vodum_users u
                                    LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
                                    LEFT JOIN media_users mu ON mu.vodum_user_id = u.id
                                    LEFT JOIN servers s ON s.id = mu.server_id
                                    LEFT JOIN media_user_libraries mul ON mul.media_user_id = mu.id
                                """

            conditions = []
            params = []

            if status_none_requested:
                conditions.append("1 = 0")
            elif selected_statuses:
                placeholders = ",".join(["?"] * len(selected_statuses))
                conditions.append(f"u.status IN ({placeholders})")
                params.extend(selected_statuses)

            if search:
                like = f"%{search}%"
                conditions.append(
                    "("
                    "COALESCE(u.username,'') LIKE ? OR "
                    "COALESCE(u.email,'') LIKE ? OR "
                    "COALESCE(u.second_email,'') LIKE ? OR "
                    "COALESCE(u.firstname,'') LIKE ? OR "
                    "COALESCE(u.lastname,'') LIKE ? OR "
                    "COALESCE(u.notes,'') LIKE ? OR "
                    "EXISTS ("
                    "   SELECT 1 FROM media_users mu_search "
                    "   WHERE mu_search.vodum_user_id = u.id "
                    "   AND COALESCE(mu_search.username,'') LIKE ?"
                    ")"
                    ")"
                )

                params.extend([
                    like,  # username
                    like,  # email
                    like,  # second_email
                    like,  # firstname
                    like,  # lastname
                    like,  # notes
                    like,  # media_users.username
                ])

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += f"""
                GROUP BY u.id
                ORDER BY
                    CASE
                        WHEN u.status IN ('active', 'pre_expired', 'reminder') THEN 0
                        ELSE 1
                    END ASC,

                    CASE
                        WHEN {sort_column} IS NULL OR {sort_column} = '' THEN 1
                        ELSE 0
                    END ASC,

                    {sort_column} {order.upper()},
                    LOWER(COALESCE(u.username, '')) ASC,
                    u.id ASC
                LIMIT ?
                OFFSET ?
            """
            params.extend([per_page, offset])

            count_query = """
                SELECT COUNT(DISTINCT u.id) as total
                FROM vodum_users u
                LEFT JOIN media_users mu ON mu.vodum_user_id = u.id
                LEFT JOIN media_user_libraries mul ON mul.media_user_id = mu.id
            """
            if conditions:
                count_query += " WHERE " + " AND ".join(conditions)

            count_params = params[:-2]
            total_row = db.query_one(count_query, count_params) or {"total": 0}
            total_users = int(total_row["total"] or 0)
            pagination = page_bounds(page, per_page, total_users)
            total_pages = pagination["total_pages"]

            if page > total_pages:
                page = total_pages
                offset = (page - 1) * per_page
                params = count_params + [per_page, offset]

            users = db.query(query, params) or []

        # --------------------------------------------------
        # TAB = REFERRALS
        # --------------------------------------------------
        elif tab == "referrals":
            sort_map = {
                "referrer": "referrer_username",
                "referred": "referred_username",
                "status": "r.status",
                "start_at": "r.start_at",
                "qualification_due_at": "r.qualification_due_at",
                "reward_granted_at": "r.reward_granted_at",
                "reward_days_snapshot": "r.reward_days_snapshot",
                "referrer_total": "referrer_total",
            }
            sort_column = sort_map.get(sort, "r.start_at")

            query = f"""
                SELECT
{USER_REFERRAL_LIST_COLUMNS},
                    referrer.username AS referrer_username,
                    referrer.email AS referrer_email,
                    referred.username AS referred_username,
                    referred.email AS referred_email,
                    referred.status AS referred_status,
                    (
                        SELECT COUNT(*)
                        FROM user_referrals rr
                        WHERE rr.referrer_user_id = r.referrer_user_id
                    ) AS referrer_total
                FROM user_referrals r
                JOIN vodum_users referrer ON referrer.id = r.referrer_user_id
                JOIN vodum_users referred ON referred.id = r.referred_user_id
            """

            conditions = []
            params = []
            archive_mode = (
                request.args.get("archive_mode", "active")
                .strip()
                .lower()
            )

            if archive_mode not in ("active", "archived", "all"):
                archive_mode = "active"

            if archive_mode == "active":
                conditions.append("r.status != 'archived'")
            elif archive_mode == "archived":
                conditions.append("r.status = 'archived'")

            if status_none_requested:
                conditions.append("1 = 0")
            elif selected_statuses:
                placeholders = ",".join(["?"] * len(selected_statuses))
                conditions.append(f"r.status IN ({placeholders})")
                params.extend(selected_statuses)

            if search:
                like = f"%{search}%"
                conditions.append(
                    "("
                    "COALESCE(referrer.username,'') LIKE ? OR "
                    "COALESCE(referrer.email,'') LIKE ? OR "
                    "COALESCE(referred.username,'') LIKE ? OR "
                    "COALESCE(referred.email,'') LIKE ?"
                    ")"
                )
                params.extend([like, like, like, like])

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += f"""
                ORDER BY
                    CASE WHEN {sort_column} IS NULL OR {sort_column} = '' THEN 1 ELSE 0 END ASC,
                    {sort_column} {order.upper()},
                    r.id DESC
                LIMIT ?
                OFFSET ?
            """
            params.extend([per_page, offset])

            count_query = """
                SELECT COUNT(*) AS total
                FROM user_referrals r
                JOIN vodum_users referrer ON referrer.id = r.referrer_user_id
                JOIN vodum_users referred ON referred.id = r.referred_user_id
            """
            if conditions:
                count_query += " WHERE " + " AND ".join(conditions)

            count_params = params[:-2]
            total_row = db.query_one(count_query, count_params) or {"total": 0}
            total_referrals = int(total_row["total"] or 0)
            pagination = page_bounds(page, per_page, total_referrals)
            total_pages = pagination["total_pages"]

            if page > total_pages:
                page = total_pages
                offset = (page - 1) * per_page
                params = count_params + [per_page, offset]

            referrals = db.query(query, params) or []

        settings = db.query_one("SELECT default_subscription_days FROM settings WHERE id = 1") if tab == "users" else None
        settings = dict(settings) if settings else {}

        resp = make_response(render_template(
            "users/users.html",
            tab=tab,
            users=users,
            referrals=referrals,
            referral_settings=referral_settings,
            referral_stats=referral_stats,
            page=page,
            total_pages=total_pages,
            total_users=total_users,
            total_referrals=total_referrals,
            selected_statuses=selected_statuses,
            status_none_requested=status_none_requested,
            search=search,
            sort=sort,
            order=order,
            per_page=per_page,
            subscription_templates=subscription_templates,
            settings=settings,
            archive_mode=archive_mode,
            active_page="users",
        ))

        if tab == "users":
            resp.set_cookie("users_list_sort", str(sort), max_age=60 * 60 * 24 * 365)
            resp.set_cookie("users_list_order", str(order), max_age=60 * 60 * 24 * 365)
            resp.set_cookie("users_list_statuses", json.dumps(selected_statuses), max_age=60 * 60 * 24 * 365)

        return resp

    @app.route("/users/referrals/bulk-status", methods=["POST"])
    def referrals_bulk_status():
        action = (request.form.get("action") or "").strip().lower()
        referral_ids = normalize_referral_ids(request.form.getlist("referral_ids"))

        if not referral_ids:
            flash("referral_bulk_no_selection", "warning")
        else:
            try:
                affected = bulk_update_referrals(get_db(), referral_ids, action)
            except ValueError:
                flash("referral_bulk_invalid_action", "error")
            else:
                message = (
                    "referral_bulk_archived"
                    if action == "archive"
                    else "referral_bulk_restored"
                )
                flash(message, "success" if affected else "warning")

        archive_mode = (request.form.get("return_archive_mode") or "active").strip()
        if archive_mode not in {"active", "archived", "all"}:
            archive_mode = "active"
        page = max(request.form.get("return_page", 1, type=int), 1)
        search = " ".join((request.form.get("return_q") or "").split()).strip()
        sort = (request.form.get("return_sort") or "created_at").strip()
        order = (request.form.get("return_order") or "desc").strip().lower()
        selected_statuses = request.form.getlist("return_status")
        return redirect(url_for(
            "users_list",
            tab="referrals",
            archive_mode=archive_mode,
            page=page,
            q=search,
            status=selected_statuses,
            sort=sort,
            order=order,
        ))
        
    @app.route("/users/referral-settings", methods=["POST"])
    def users_referral_settings_save():
        db = get_db()

        enabled = 1 if request.form.get("enabled") == "1" else 0
        reward_enabled = 1 if request.form.get("reward_enabled") == "1" else 0
        allow_referrer_change_before_qualification = 1 if request.form.get("allow_referrer_change_before_qualification") == "1" else 0
        auto_notify_reward = 1 if request.form.get("auto_notify_reward") == "1" else 0
        auto_expire_pending = 1 if request.form.get("auto_expire_pending") == "1" else 0
        auto_archive_rewarded = 1 if request.form.get("auto_archive_rewarded") == "1" else 0
        auto_archive_expired = 1 if request.form.get("auto_archive_expired") == "1" else 0

        try:
            qualification_days = max(int(request.form.get("qualification_days") or 60), 1)
        except Exception:
            qualification_days = 60

        try:
            reward_days = max(int(request.form.get("reward_days") or 60), 0)
        except Exception:
            reward_days = 60
        try:
            rewarded_archive_days = max(
                int(request.form.get("rewarded_archive_days") or 90),
                1
            )
        except Exception:
            rewarded_archive_days = 90

        try:
            expired_archive_days = max(
                int(request.form.get("expired_archive_days") or 30),
                1
            )
        except Exception:
            expired_archive_days = 30


        eligible_statuses = request.form.getlist("eligible_statuses")
        if not eligible_statuses:
            eligible_statuses = ["active"]

        db.execute(
            """
            UPDATE user_referral_settings
            SET enabled = ?,
                reward_enabled = ?,
                qualification_days = ?,
                reward_days = ?,
                allow_referrer_change_before_qualification = ?,
                auto_notify_reward = ?,

                auto_expire_pending = ?,
                auto_archive_rewarded = ?,
                auto_archive_expired = ?,

                rewarded_archive_days = ?,
                expired_archive_days = ?,

                eligible_statuses = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                enabled,
                reward_enabled,
                qualification_days,
                reward_days,
                allow_referrer_change_before_qualification,
                auto_notify_reward,

                auto_expire_pending,
                auto_archive_rewarded,
                auto_archive_expired,

                rewarded_archive_days,
                expired_archive_days,

                ",".join(eligible_statuses),
            ),
        )

        flash("referral_settings_saved", "success")
        return redirect(url_for("users_list", tab="referral_settings"))


    @app.route("/users/<int:user_id>/merge/preview", methods=["GET"])
    def user_merge_preview(user_id: int):
        db = get_db()

        other_id = request.args.get("other_id", type=int)
        if not other_id:
            return Response(json.dumps({"error": "missing_other_id"}), status=400, mimetype="application/json")

        master = db.query_one(f"SELECT {USER_MERGE_COLUMNS} FROM vodum_users WHERE id=?", (user_id,))
        other = db.query_one(f"SELECT {USER_MERGE_COLUMNS} FROM vodum_users WHERE id=?", (other_id,))
        if not master or not other:
            return Response(json.dumps({"error": "user_not_found"}), status=404, mimetype="application/json")

        master = dict(master)
        other = dict(other)

        preview = build_merge_preview(master, other)

        # Bonus: compter ce qui sera déplacé (utile à afficher)
        changes = {
            "media_users_to_move": db.query_one("SELECT COUNT(*) AS c FROM media_users WHERE vodum_user_id=?", (other_id,))["c"],
            "identities_to_move": db.query_one("SELECT COUNT(*) AS c FROM user_identities WHERE vodum_user_id=?", (other_id,))["c"],
            "sent_emails_to_move": db.query_one("SELECT COUNT(*) AS c FROM sent_emails WHERE user_id=?", (other_id,))["c"],
            "media_jobs_to_move": db.query_one("SELECT COUNT(*) AS c FROM media_jobs WHERE vodum_user_id=?", (other_id,))["c"],
        }

        payload = {
            "master_id": user_id,
            "other_id": other_id,
            "result": preview["result"],
            "sources": preview["sources"],
            "changes": changes,
        }
        return Response(json.dumps(payload, default=str), mimetype="application/json")

    return app

# user merge control
##################################
