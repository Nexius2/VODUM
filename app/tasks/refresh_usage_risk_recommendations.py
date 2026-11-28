"""Refresh recommendation history independently of page visits and delivery."""

from core.usage_risk import build_usage_risk_report


def run(task_id, db):
    report = build_usage_risk_report(db, persist_history=True)
    return {
        "status": "success",
        "recommendations": report["summary"]["suggested"],
    }
