"""Optional global limit on the media requests each portal member may send.

Disabled by default. It applies to the requests sent from the portal, with the
VODUM (Sonarr/Radarr) engine as with Seerr; requests made directly in Seerr are
not seen by VODUM and are not counted.
"""

import sqlite3

QUOTA_PERIODS = (1, 7, 30)
DEFAULT_QUOTA_COUNT = 10
DEFAULT_QUOTA_DAYS = 7
MAX_QUOTA_COUNT = 1000
# Results that created a request; duplicates, present media and failures are free.
COUNTED_RESULTS = ("portal_requests_added", "portal_requests_seerr_awaiting_approval")


def quota_settings(db):
    """Return (count, days) when the quota is enabled, otherwise None."""
    try:
        row = db.query_one("""
            SELECT portal_request_quota_enabled, portal_request_quota_count, portal_request_quota_days
            FROM settings WHERE id = 1
        """)
    except sqlite3.OperationalError:
        return None  # Columns not created yet: no quota, as by default.
    values = dict(row) if row else {}
    if int(values.get("portal_request_quota_enabled") or 0) != 1:
        return None
    try:
        count = int(values.get("portal_request_quota_count"))
        days = int(values.get("portal_request_quota_days"))
    except (TypeError, ValueError):
        return None
    if not 1 <= count <= MAX_QUOTA_COUNT or days not in QUOTA_PERIODS:
        return None
    return count, days


def quota_used(cursor, account_id, days):
    """Requests created in the last ``days`` days plus requests still in progress."""
    created = cursor.execute(
        """
        SELECT COUNT(*) AS used FROM portal_audit_events
        WHERE portal_account_id = ? AND event_type = 'media_requested' AND outcome = 'success'
          AND created_at >= datetime('now', ?)
          AND json_extract(details_json, '$.request_result') IN (%s)
        """ % ",".join("?" * len(COUNTED_RESULTS)),
        (account_id, f"-{int(days)} days", *COUNTED_RESULTS),
    ).fetchone()
    in_progress = cursor.execute(
        "SELECT COUNT(*) AS used FROM portal_media_request_jobs WHERE account_id = ? AND status <> 'done'",
        (account_id,),
    ).fetchone()
    return int(created["used"] or 0) + int(in_progress["used"] or 0)


def normalize_quota_form(form):
    """Admin form values; invalid numbers fall back to the defaults with an error."""
    errors = []
    enabled = 1 if form.get("portal_request_quota_enabled") == "1" else 0
    try:
        count = int(form.get("portal_request_quota_count", DEFAULT_QUOTA_COUNT))
        if not 1 <= count <= MAX_QUOTA_COUNT:
            raise ValueError()
    except (TypeError, ValueError):
        count = DEFAULT_QUOTA_COUNT
        if enabled:
            errors.append("portal_requests_options_invalid")
    try:
        days = int(form.get("portal_request_quota_days", DEFAULT_QUOTA_DAYS))
        if days not in QUOTA_PERIODS:
            raise ValueError()
    except (TypeError, ValueError):
        days = DEFAULT_QUOTA_DAYS
        if enabled:
            errors.append("portal_requests_options_invalid")
    return {"portal_request_quota_enabled": enabled, "portal_request_quota_count": count,
            "portal_request_quota_days": days}, errors
