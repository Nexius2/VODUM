"""Background views read by the dashboard, user pages and portal.

Each builder runs only in the ``refresh_monitoring_statistics`` task. HTTP
handlers call the ``load_*`` readers, which read one stored row and never run
the builders.
"""

from core.monitoring.precomputed import load_snapshot


def _usage_risk_report(db, options):
    from core.usage_risk import build_usage_risk_report
    return build_usage_risk_report(db, {"period_days": int(options["period_days"])}, persist_history=False)


def _server_peaks(db, options):
    if not db.query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_session_history'"):
        return []
    return [dict(row) for row in (db.query(
        """
        WITH events AS (
            SELECT server_id, datetime(started_at) AS ts, 1 AS delta
            FROM media_session_history WHERE datetime(stopped_at) >= datetime('now', '-7 days')
            UNION ALL
            SELECT server_id, datetime(stopped_at) AS ts, -1 AS delta
            FROM media_session_history WHERE datetime(stopped_at) >= datetime('now', '-7 days')
        ), running AS (
            SELECT server_id, SUM(delta) OVER (
                PARTITION BY server_id ORDER BY ts
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS active_count FROM events
        )
        SELECT server_id, MAX(active_count) AS peak FROM running GROUP BY server_id
        """
    ) or [])]


def _monitoring_user(db, options):
    from core.monitoring.user_detail_stats import compute_monitoring_user_stats
    return compute_monitoring_user_stats(db, options)


def _portal_user(db, options):
    from core.portal_page_data import compute_portal_statistics
    return compute_portal_statistics(db, int(options["vodum_user_id"]))


def _merge_suggestions(db, options):
    from core.user_merge_suggestions import get_merge_suggestions
    # Only the ranking is stored; the picker reads the current accounts.
    return [[int(row["id"]), int(row["merge_score"])]
            for row in get_merge_suggestions(db, int(options["vodum_user_id"]), limit=None)
            if int(row.get("merge_score") or 0) > 0]


BUILDERS = {
    "usage_risk_report": _usage_risk_report,
    "server_peaks": _server_peaks,
    "monitoring_user": _monitoring_user,
    "portal_user": _portal_user,
    "merge_suggestions": _merge_suggestions,
}


def load_usage_risk_report(db, period_days):
    return load_snapshot(db, f"usage_risk:{int(period_days)}d", "usage_risk_report", {"period_days": int(period_days)})


def load_server_peaks(db):
    rows, metadata = load_snapshot(db, "server_peaks:7d", "server_peaks", {})
    return None if rows is None else {int(row["server_id"]): int(row["peak"] or 0) for row in rows if row.get("server_id") is not None}, metadata


def load_monitoring_user_stats(db, media_user_id):
    return load_snapshot(db, f"monitoring_user:{int(media_user_id)}", "monitoring_user", {"media_user_id": int(media_user_id)})


def load_portal_statistics(db, vodum_user_id, register=True):
    return load_snapshot(db, f"portal_user:{int(vodum_user_id)}", "portal_user", {"vodum_user_id": int(vodum_user_id)},
                         register=register)


def load_merge_scores(db, vodum_user_id):
    rows, metadata = load_snapshot(db, f"merge_suggestions:{int(vodum_user_id)}", "merge_suggestions", {"vodum_user_id": int(vodum_user_id)})
    return None if rows is None else {int(identifier): int(score) for identifier, score in rows}, metadata
