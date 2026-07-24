from __future__ import annotations

import json
import math


COMM_HISTORY_COLUMNS = """
                h.id,
                h.kind,
                h.status,
                h.sent_at,
                h.error,
                h.meta_json,
                h.template_id,
                h.campaign_id
"""


def _safe_page(value) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _history_order_sql(alias="h"):
    return f"""
        COALESCE(
            CASE
                WHEN typeof({alias}.sent_at) = 'integer' THEN {alias}.sent_at
                WHEN typeof({alias}.sent_at) = 'text'
                  AND {alias}.sent_at GLOB '[0-9]*'
                    THEN CAST({alias}.sent_at AS INTEGER)
                ELSE CAST(strftime('%s', {alias}.sent_at) AS INTEGER)
            END,
            0
        ) DESC,
        {alias}.id DESC
    """


def _build_history_label(row):
    try:
        meta = json.loads(row.get("meta_json") or "{}")
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}

    if (row.get("kind") or "").strip().lower() == "campaign":
        return (row.get("campaign_name") or "").strip() or "Campaign"
    return (
        (row.get("template_key") or "").strip()
        or (row.get("template_name") or "").strip()
        or (meta.get("template_key") or "").strip()
        or "Template"
    )


def load_user_notification_history(
    db,
    user_id: int,
    email_page_value=None,
    discord_page_value=None,
    *,
    enabled: bool,
    per_page: int = 10,
):
    if not enabled:
        return {
            "sent_emails": [],
            "sent_discord": [],
            "email_page": 1,
            "email_pages": 1,
            "email_total": 0,
            "discord_page": 1,
            "discord_pages": 1,
            "discord_total": 0,
            "per_page": per_page,
        }

    totals = {}
    pages = {}
    requested_pages = {
        "email": _safe_page(email_page_value),
        "discord": _safe_page(discord_page_value),
    }
    history = {}

    for channel in ("email", "discord"):
        total_row = db.query_one(
            """
            SELECT COUNT(*) AS c
            FROM comm_history h
            WHERE h.user_id = ?
              AND h.channel_used = ?
            """,
            (user_id, channel),
        )
        total = (total_row["c"] if total_row else 0) or 0
        page_count = max(1, math.ceil(total / per_page)) if total else 1
        page = min(requested_pages[channel], page_count)
        rows = db.query(
            f"""
            SELECT
{COMM_HISTORY_COLUMNS},
                ct.key AS template_key,
                ct.name AS template_name,
                cc.name AS campaign_name
            FROM comm_history h
            LEFT JOIN comm_templates ct ON ct.id = h.template_id
            LEFT JOIN comm_campaigns cc ON cc.id = h.campaign_id
            WHERE h.user_id = ?
              AND h.channel_used = ?
            ORDER BY {_history_order_sql("h")}
            LIMIT ? OFFSET ?
            """,
            (user_id, channel, per_page, (page - 1) * per_page),
        ) or []

        items = []
        for row in rows:
            item = dict(row)
            item["label"] = _build_history_label(item)
            items.append(item)
        totals[channel] = total
        pages[channel] = (page, page_count)
        history[channel] = items

    return {
        "sent_emails": history["email"],
        "sent_discord": history["discord"],
        "email_page": pages["email"][0],
        "email_pages": pages["email"][1],
        "email_total": totals["email"],
        "discord_page": pages["discord"][0],
        "discord_pages": pages["discord"][1],
        "discord_total": totals["discord"],
        "per_page": per_page,
    }
