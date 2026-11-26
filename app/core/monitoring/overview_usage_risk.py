from __future__ import annotations

from core.usage_risk import build_usage_risk_report


def _integer(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_usage_risk_filters(args):
    return {
        "q": (args.get("q") or "").strip(),
        "risk_level": (args.get("risk_level") or "").strip(),
        "subscription_id": _integer(args.get("subscription_id"), 0),
        "server_id": _integer(args.get("server_id"), 0),
        "policy": (args.get("policy") or "").strip(),
        "period_days": _integer(args.get("period_days"), 30),
    }


def load_usage_risk_context(db, args):
    filters = build_usage_risk_filters(args)
    report = build_usage_risk_report(db, filters)
    templates = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT id, name
                FROM subscription_templates
                WHERE is_enabled = 1
                ORDER BY subscription_value ASC, name ASC
                """
            )
            or []
        )
    ]
    policy_types = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT DISTINCT rule_type
                FROM stream_policies
                WHERE TRIM(COALESCE(rule_type, '')) <> ''
                ORDER BY rule_type ASC
                """
            )
            or []
        )
    ]
    return {
        "usage_risk_filters": filters,
        "usage_risk_report": report,
        "subscription_templates": templates,
        "stream_policy_types": policy_types,
    }
