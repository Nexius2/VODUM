"""Compare the latest conclusive synchronization across a configuration's libraries."""

import json


INFORMATIONAL_WARNINGS = {
    "collections.limit_shortfall", "collections.arr_pending",
    "collections.jellyfin_order_not_supported", "collections.jellyfin_home_not_supported",
}


def actionable_collection_warnings(warnings):
    """Keep genuine warnings while retaining expected limitations in run details."""
    return [code for code in warnings
            if not isinstance(code, str) or code.split(":", 1)[0] not in INFORMATIONAL_WARNINGS]



def load_collection_sync_issues(db):
    rows = db.query("""
        SELECT COALESCE(NULLIF(i.group_id, ''), i.id) AS configuration_id,
               i.library_id, COALESCE(snapshot.state, r.state) AS state,
               COALESCE(snapshot.reasons_json, json_object(
                   'warnings', json_extract(r.result_json, '$.warnings'),
                   'errors', json_extract(r.result_json, '$.errors')
               )) AS reasons_json
        FROM collection_instances i
        LEFT JOIN collection_last_sync snapshot ON snapshot.instance_id = i.id
        LEFT JOIN collection_runs r ON r.id = (
          SELECT recent.id
          FROM collection_runs recent
          WHERE snapshot.instance_id IS NULL AND recent.instance_id = i.id
            AND recent.kind = 'sync' AND recent.finished_at IS NOT NULL
            AND recent.state IN ('success', 'warning', 'error')
          ORDER BY recent.id DESC
          LIMIT 1
        )
        WHERE i.retired = 0
        ORDER BY i.library_id, i.id
    """)
    configurations = {}
    for row in rows:
        issues = configurations.setdefault(row["configuration_id"], [])
        state = row["state"]
        if state == "success":
            continue
        details = json.loads(row["reasons_json"])
        warnings = details.get("warnings") or []
        errors = details.get("errors") or []
        actionable = actionable_collection_warnings(warnings)
        if state == "warning" and warnings and not actionable and not errors:
            continue
        reasons = errors if state == "error" else errors + actionable
        issues.append({
            "library_id": row["library_id"], "state": state,
            "reasons": list(dict.fromkeys(reason.split(":", 1)[0] for reason in reasons)),
        })
    return configurations
