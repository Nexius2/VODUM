"""Read-only data builders for dashboard widgets."""

from collections import Counter

from core.aggregate_cache import cached_aggregate
from core.dashboard_servers import dashboard_server_preview
from core.dashboard_usage_risk import build_usage_risk_trend
from core.usage_risk import build_usage_risk_report
from web.helpers import table_exists


def get_dashboard_next_tasks(db):
    if not table_exists(db, "tasks"):
        return {
            "items": [],
            "active": 0,
            "error": 0,
        }

    row = db.query_one(
        """
        SELECT
          SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS active,
          SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error
        FROM tasks
        """
    )

    tasks = db.query(
        """
        SELECT
          name,
          status,
          next_run,
          last_run
        FROM tasks
        WHERE enabled = 1
        ORDER BY
          CASE WHEN next_run IS NULL THEN 1 ELSE 0 END,
          datetime(next_run) ASC,
          LOWER(name) ASC
        LIMIT 8
        """
    ) or []

    return {
        "items": [dict(t) for t in tasks],
        "active": int((row["active"] if row else 0) or 0),
        "error": int((row["error"] if row else 0) or 0),
    }

def get_dashboard_subscription_summary(db):
    kills_7d = 0
    if table_exists(db, "stream_enforcements"):
        row = db.query_one(
            """
            SELECT COUNT(*) AS cnt
            FROM stream_enforcements
            WHERE action = 'kill'
              AND datetime(created_at) >= datetime('now', '-7 days')
            """
        )
        kills_7d = int(row["cnt"] or 0) if row else 0

    subscription_stats = []
    if table_exists(db, "subscription_templates"):
        subscription_stats = [dict(row) for row in (db.query(
            """
            SELECT st.id, st.name, COUNT(vu.id) AS user_count
            FROM subscription_templates st
            LEFT JOIN vodum_users vu ON vu.subscription_template_id = st.id
            WHERE COALESCE(st.is_enabled, 1) = 1
            GROUP BY st.id, st.name
            ORDER BY user_count DESC, LOWER(st.name) ASC
            """
        ) or [])]

    user_total = sum(int(item.get("user_count") or 0) for item in subscription_stats)
    colors = ["#8b5cf6", "#f97316", "#60a5fa", "#22c55e", "#f43f5e", "#eab308", "#14b8a6", "#a78bfa"]
    donut_parts = []
    cursor = 0.0

    for index, item in enumerate(subscription_stats):
        count = int(item.get("user_count") or 0)
        percent = round((count / user_total) * 100, 1) if user_total else 0.0
        item["percent"] = percent
        item["color"] = colors[index % len(colors)]
        if count > 0 and user_total > 0:
            donut_parts.append(f"{item['color']} {cursor:.2f}% {cursor + percent:.2f}%")
            cursor += percent

    return {
        "kills_7d": kills_7d,
        "subscription_stats": subscription_stats,
        "subscription_stats_more": len(subscription_stats) > 8,
        "subscription_plan_count": len(subscription_stats),
        "subscription_donut": ", ".join(donut_parts) if donut_parts else "#334155 0% 100%",
    }

def _build_usage_risk_dashboard(usage_risk_report, history_rows=None):
    rows = usage_risk_report.get("rows") or []

    reasons_counter = Counter()
    for row in rows:
        for reason in row.get("reasons") or []:
            reasons_counter[str(reason)] += 1

    total_reasons = sum(reasons_counter.values()) or 0
    top_reasons = []

    for label, count in reasons_counter.most_common(3):
        percent = round((count / total_reasons) * 100, 1) if total_reasons else 0
        top_reasons.append({
            "label": label,
            "count": count,
            "percent": percent,
        })

    result = {
        "top_reasons": top_reasons,
    }
    result.update(
        build_usage_risk_trend(
            history_rows or [],
            usage_risk_report.get("summary", {}).get("suggested", 0),
        )
    )
    return result

def get_dashboard_usage_risk(db):
    summary = {"high": 0, "medium": 0, "low": 0, "suggested": 0}
    dashboard = {"top_reasons": [], **build_usage_risk_trend([], 0)}
    try:
        report = cached_aggregate(
            "dashboard:usage-risk:30d",
            60,
            lambda: build_usage_risk_report(db, {"period_days": 30}, persist_history=False),
        )
        summary = report.get("summary") or summary
        history = []
        if table_exists(db, "usage_risk_recommendations"):
            history = db.query(
                """
                SELECT vodum_user_id, first_detected_at, last_detected_at
                FROM usage_risk_recommendations
                WHERE datetime(first_detected_at) <= datetime('now')
                  AND datetime(last_detected_at) >= datetime('now', '-13 days', 'start of day')
                """
            ) or []
        dashboard = _build_usage_risk_dashboard(report, history)
    except Exception:
        pass
    return summary, dashboard

def get_dashboard_servers(db):
    servers = [dict(row) for row in (db.query(
        """
        SELECT s.id, s.name, s.type,
               COALESCE(s.url, s.local_url, s.public_url) AS url,
               s.status, s.last_checked
        FROM servers s
        ORDER BY s.type, s.name
        """
    ) or [])]
    for server in servers:
        server["peak_streams_7d"] = 0

    if table_exists(db, "media_session_history"):
        rows = cached_aggregate(
            "dashboard:server-peaks:7d",
            120,
            lambda: [dict(row) for row in (db.query(
                """
                WITH events AS (
                    SELECT server_id, datetime(started_at) AS ts, 1 AS delta
                    FROM media_session_history WHERE stopped_at >= datetime('now', '-7 days')
                    UNION ALL
                    SELECT server_id, datetime(stopped_at) AS ts, -1 AS delta
                    FROM media_session_history WHERE stopped_at >= datetime('now', '-7 days')
                ), running AS (
                    SELECT server_id, SUM(delta) OVER (
                        PARTITION BY server_id ORDER BY ts
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS active_count FROM events
                )
                SELECT server_id, MAX(active_count) AS peak FROM running GROUP BY server_id
                """
            ) or [])],
        )
        peaks = {int(row["server_id"]): int(row["peak"] or 0) for row in rows}
        for server in servers:
            server["peak_streams_7d"] = peaks.get(int(server["id"]), 0)

    return servers, dashboard_server_preview(servers)
