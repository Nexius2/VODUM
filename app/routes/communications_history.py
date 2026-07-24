import json

from flask import jsonify, render_template, request

from core.communication_history_rendering import render_communication_history_message as _render_comm_history_message
from core.communication_page_data import load_history_detail
from web.helpers import get_db


COMM_HISTORY_COLUMNS = """
    h.id,
    h.kind,
    h.template_id,
    h.campaign_id,
    h.channel_used,
    h.status,
    h.error,
    h.sent_at,
    h.meta_json
"""


def _as_int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def register_history_routes(app):
    @app.route("/communications/history")
    def communications_history_page():
        db = get_db()

        page = max(_as_int(request.args.get("page"), 1), 1)
        per_page = _as_int(request.args.get("per_page"), 20)
        if per_page not in (20, 50, 100):
            per_page = 20

        sort = (request.args.get("sort") or "sent_at").strip().lower()
        order = (request.args.get("order") or "").strip().lower()

        if sort == "sent_at" and not order:
            order = "desc"

        if order not in ("asc", "desc"):
            order = "asc"

        if sort == "sent_at" and order == "asc" and not request.args.get("order"):
            order = "desc"

        trigger_filter = (request.args.get("trigger") or "").strip().lower()
        trigger_options = [
            ("", "All communications"),
            ("usage_risk_upgrade_suggestion", "Upgrade suggestions"),
            ("stream_blocked", "Stream blocked"),
            ("expiration", "Expiration"),
            ("expiration_change", "Expiration changes"),
            ("user_creation", "User creation"),
            ("pending_invite_reminder", "Pending invites"),
            ("referral_reward", "Referral rewards"),
        ]
        allowed_triggers = {value for value, _label in trigger_options if value}
        if trigger_filter not in allowed_triggers:
            trigger_filter = ""

        sent_at_sort_expr = """
            COALESCE(
                CASE
                    WHEN typeof(h.sent_at) = 'integer' THEN h.sent_at
                    WHEN typeof(h.sent_at) = 'text' AND h.sent_at GLOB '[0-9][0-9][0-9][0-9]-*' THEN CAST(strftime('%s', h.sent_at) AS INTEGER)
                    WHEN typeof(h.sent_at) = 'text' AND h.sent_at GLOB '[0-9]*' THEN CAST(h.sent_at AS INTEGER)
                    ELSE CAST(strftime('%s', h.sent_at) AS INTEGER)
                END,
                0
            )
        """

        sort_map = {
            "kind": "LOWER(COALESCE(h.kind, ''))",
            "user": "LOWER(COALESCE(u.username, ''))",
            "channel_used": "LOWER(COALESCE(h.channel_used, ''))",
            "status": "LOWER(COALESCE(h.status, ''))",
            "error": "LOWER(COALESCE(h.error, ''))",
            "sent_at": sent_at_sort_expr,
        }

        if sort not in sort_map:
            sort = "sent_at"

        order_sql = "ASC" if order == "asc" else "DESC"
        order_by_sql = f"{sort_map[sort]} {order_sql}, h.id DESC"

        history_where = []
        history_params = []
        if trigger_filter:
            history_where.append("(t.trigger_event = ? OR h.meta_json LIKE ?)")
            history_params.extend([trigger_filter, f"%{trigger_filter}%"])
        history_where_sql = f"WHERE {' AND '.join(history_where)}" if history_where else ""

        total_row = db.query_one(
            f"""
            SELECT COUNT(*) AS total
            FROM comm_history h
            LEFT JOIN comm_templates t ON t.id = h.template_id
            {history_where_sql}
            """,
            tuple(history_params),
        )
        total_rows = int(total_row["total"]) if total_row and total_row["total"] is not None else 0
        total_pages = max((total_rows + per_page - 1) // per_page, 1)

        summary_row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN channel_used='email' AND status='sent' THEN 1 ELSE 0 END) AS email_sent,
              SUM(CASE WHEN channel_used='email' AND status='failed' THEN 1 ELSE 0 END) AS email_failed,
              SUM(CASE WHEN channel_used='discord' AND status='sent' THEN 1 ELSE 0 END) AS discord_sent,
              SUM(CASE WHEN channel_used='discord' AND status='failed' THEN 1 ELSE 0 END) AS discord_failed,
              SUM(CASE WHEN status='sent' AND datetime(sent_at) >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) AS sent_24h,
              SUM(CASE WHEN status='failed' AND datetime(sent_at) >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) AS failed_24h
            FROM comm_history
            """
        ) or {}
        communication_summary = dict(summary_row)
        queue_row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM comm_scheduled
            """
        ) or {}
        communication_summary.update(dict(queue_row))
        communication_summary = {
            key: int(value or 0)
            for key, value in communication_summary.items()
        }

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * per_page

        settings_row = db.query_one("SELECT brand_name FROM settings WHERE id = 1")
        settings = dict(settings_row) if settings_row else {}
        brand_name = settings.get("brand_name") or "VODUM"

        rows = db.query(
            f"""
            SELECT
                {COMM_HISTORY_COLUMNS},
                u.id AS user_id,
                u.username AS user_username,
                u.firstname AS user_firstname,
                u.lastname AS user_lastname,
                u.email AS user_email,
                u.expiration_date AS user_expiration_date,
                u.subscription_template_id AS user_subscription_template_id,
                st.name AS subscription_name,
                st.duration_days AS subscription_duration_days,
                st.subscription_value AS subscription_value,
                t.key AS template_key,
                t.subject AS template_subject,
                t.body AS template_body,
                c.name AS campaign_name,
                c.subject AS campaign_subject,
                c.body AS campaign_body
            FROM comm_history h
            LEFT JOIN vodum_users u ON u.id = h.user_id
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            LEFT JOIN comm_templates t ON t.id = h.template_id
            LEFT JOIN comm_campaigns c ON c.id = h.campaign_id
            {history_where_sql}
            ORDER BY {order_by_sql}
            LIMIT ? OFFSET ?
            """,
            (*history_params, per_page, offset),
        )


        history = [dict(r) for r in (rows or [])]

        scheduled_where = "AND t.trigger_event = ?" if trigger_filter else ""
        scheduled_params = (trigger_filter,) if trigger_filter else ()

        scheduled_rows = db.query(
            f"""
            SELECT
              q.id,
              q.status,
              q.send_at,
              q.next_attempt_at,
              q.last_attempt_at,
              q.attempt_count,
              q.max_attempts,
              q.last_error,
              q.channels_sent,
              q.dedupe_key,
              q.updated_at,
              q.payload_json,
              t.id AS template_id,
              t.key AS template_key,
              t.subject AS template_subject,
              t.body AS template_body,
              t.trigger_event,
              u.id AS user_id,
              u.username AS user_username,
              u.firstname AS user_firstname,
              u.lastname AS user_lastname,
              u.email AS user_email,
              u.expiration_date AS user_expiration_date,
              u.subscription_template_id AS user_subscription_template_id,
              st.name AS subscription_name,
              st.duration_days AS subscription_duration_days,
              st.subscription_value AS subscription_value
            FROM comm_scheduled q
            JOIN comm_templates t ON t.id = q.template_id
            LEFT JOIN vodum_users u ON u.id = q.vodum_user_id
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            WHERE q.status IN ('pending', 'error')
              {scheduled_where}
            ORDER BY
              CASE q.status WHEN 'error' THEN 0 ELSE 1 END,
              datetime(COALESCE(q.next_attempt_at, q.send_at, q.updated_at)) ASC,
              q.id ASC
            LIMIT 25
            """,
            scheduled_params,
        ) or []

        scheduled_history = []
        for r in scheduled_rows:
            r = dict(r)
            payload = {}
            try:
                payload = json.loads(r.get("payload_json") or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            meta = {
                "scheduled_id": r.get("id"),
                "template_key": r.get("template_key"),
                "trigger_event": r.get("trigger_event"),
                "payload": payload,
                "dedupe_key": r.get("dedupe_key"),
                "attempt_count": r.get("attempt_count") or 0,
                "max_attempts": r.get("max_attempts") or 10,
                "next_attempt_at": r.get("next_attempt_at"),
            }
            row = {
                "id": f"scheduled-{r.get('id')}",
                "kind": "template",
                "is_scheduled": True,
                "template_id": r.get("template_id"),
                "campaign_id": None,
                "user_id": r.get("user_id"),
                "user_username": r.get("user_username"),
                "user_firstname": r.get("user_firstname"),
                "user_lastname": r.get("user_lastname"),
                "user_email": r.get("user_email"),
                "user_expiration_date": r.get("user_expiration_date"),
                "user_subscription_template_id": r.get("user_subscription_template_id"),
                "subscription_name": r.get("subscription_name"),
                "subscription_duration_days": r.get("subscription_duration_days"),
                "subscription_value": r.get("subscription_value"),
                "template_key": r.get("template_key"),
                "template_subject": r.get("template_subject"),
                "template_body": r.get("template_body"),
                "campaign_name": None,
                "campaign_subject": None,
                "campaign_body": None,
                "channel_used": r.get("channels_sent") or "",
                "status": r.get("status") or "pending",
                "error": r.get("last_error") or r.get("dedupe_key") or "",
                "sent_at": r.get("last_attempt_at") or r.get("send_at"),
                "send_at": r.get("send_at"),
                "next_attempt_at": r.get("next_attempt_at"),
                "attempt_count": r.get("attempt_count") or 0,
                "max_attempts": r.get("max_attempts") or 10,
                "meta_json": json.dumps(meta, ensure_ascii=False),
            }
            scheduled_history.append(_render_comm_history_message(row, brand_name))

        if page == 1:
            history = scheduled_history + history

        return render_template(
            "communications/communications_history.html",
            history=history,
            current_subpage="history",
            page=page,
            per_page=per_page,
            total_rows=total_rows,
            total_pages=total_pages,
            sort=sort,
            order=order,
            trigger_filter=trigger_filter,
            trigger_options=trigger_options,
            communication_summary=communication_summary,
        )

    @app.route("/communications/history/<int:history_id>/detail")
    def communications_history_detail(history_id):
        item = load_history_detail(get_db(), history_id, COMM_HISTORY_COLUMNS)
        if not item:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({
            "ok": True,
            "subject": item.get("rendered_subject") or "",
            "body": item.get("rendered_body") or "",
            "meta_json": item.get("meta_json") or "{}",
        })
