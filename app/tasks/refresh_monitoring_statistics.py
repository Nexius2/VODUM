"""Refresh persisted historical Monitoring views without blocking HTTP reads."""

from core.monitoring.precomputed import refresh_snapshots


def run(task_id, db):
    result = refresh_snapshots(db)
    if result["errors"]:
        failures = '; '.join(f"{view['key']} ({view['cause']}/{view['error_type']})"
                             for view in result.get('failed_views', []))
        result.update(status="error", message=f"{result['errors']} Monitoring snapshot(s) failed: {failures}; previous data retained")
    return result
