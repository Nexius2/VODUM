"""Read-only portal usage aggregates, independent of media monitoring."""
from datetime import datetime, timedelta, timezone
import json


def load_portal_usage(db, days=30, page=1):
    days = days if days in (7, 30, 90) else 30
    page = max(1, int(page))
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days - 1)).isoformat()
    sessions = dict(db.query_one(
        "SELECT COUNT(*) AS logins, COUNT(DISTINCT portal_account_id) AS users "
        "FROM portal_sessions WHERE created_at >= ?", (start,)) or {})
    stats = dict(db.query_one(
        "SELECT COUNT(*) AS events, "
        "SUM(event_type='friend_invitation' AND outcome='success') AS invitations, "
        "SUM(event_type IN ('profile_updated','password_changed','media_profile_updated','identity_linked','identity_unlinked') AND outcome='success') AS changes, "
        "SUM(outcome IN ('failure','blocked')) AS failures, "
        "COUNT(DISTINCT CASE WHEN outcome='success' THEN portal_account_id END) AS active_users "
        "FROM portal_audit_events WHERE created_at >= ?", (start,)) or {})
    stats.update(sessions)
    stats['online'] = (db.query_one(
        "SELECT COUNT(DISTINCT portal_account_id) AS n FROM portal_sessions "
        "WHERE revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP "
        "AND last_seen_at >= datetime('now','-5 minutes')") or {})['n']
    login_days = {row['day']: row['n'] for row in db.query(
        "SELECT date(created_at) AS day, COUNT(*) AS n FROM portal_sessions "
        "WHERE created_at>=? GROUP BY day", (start,))}
    action_days = {row['day']: dict(row) for row in db.query(
        "SELECT date(created_at) AS day, SUM(event_type='friend_invitation' AND outcome='success') AS invitations, "
        "SUM(event_type IN ('profile_updated','password_changed','media_profile_updated','identity_linked','identity_unlinked') AND outcome='success') AS changes "
        "FROM portal_audit_events WHERE created_at>=? GROUP BY day", (start,))}
    timeline = []
    for offset in range(days):
        day = (today - timedelta(days=days - 1 - offset)).isoformat()
        timeline.append({'day': day, 'logins': login_days.get(day, 0),
                         'invitations': action_days.get(day, {}).get('invitations', 0),
                         'changes': action_days.get(day, {}).get('changes', 0)})
    users = [dict(row) for row in db.query(
        "SELECT a.id, a.vodum_user_id, u.username, a.status, "
        "(SELECT MAX(last_seen_at) FROM portal_sessions s WHERE s.portal_account_id=a.id) AS last_seen, "
        "(SELECT COUNT(*) FROM portal_sessions s WHERE s.portal_account_id=a.id AND s.created_at>=?) AS logins, "
        "(SELECT COUNT(*) FROM portal_audit_events e WHERE e.portal_account_id=a.id AND e.created_at>=? AND e.event_type='friend_invitation' AND e.outcome='success') AS invitations, "
        "(SELECT COUNT(*) FROM portal_audit_events e WHERE e.portal_account_id=a.id AND e.created_at>=? AND e.event_type IN ('profile_updated','password_changed','media_profile_updated','identity_linked','identity_unlinked') AND e.outcome='success') AS changes "
        "FROM portal_accounts a JOIN vodum_users u ON u.id=a.vodum_user_id "
        "ORDER BY logins DESC, last_seen DESC LIMIT 50", (start, start, start))]
    count = (db.query_one("SELECT COUNT(*) AS n FROM portal_audit_events WHERE created_at>=?", (start,)) or {})['n']
    pages = max(1, (count + 49) // 50)
    page = min(page, pages)
    events = [dict(row) for row in db.query(
        "SELECT e.created_at,e.event_type,e.outcome,u.username,a.vodum_user_id "
        "FROM portal_audit_events e LEFT JOIN portal_accounts a ON a.id=e.portal_account_id "
        "LEFT JOIN vodum_users u ON u.id=a.vodum_user_id WHERE e.created_at>=? "
        "ORDER BY e.created_at DESC,e.id DESC LIMIT 50 OFFSET ?", (start, (page - 1) * 50))]
    media_requests = []
    request_counts = {'total':0, 'added':0, 'present':0, 'pending':0, 'failed':0}
    for source in db.query(
        "SELECT e.created_at,e.outcome,e.details_json,u.username,a.vodum_user_id "
        "FROM portal_audit_events e LEFT JOIN portal_accounts a ON a.id=e.portal_account_id "
        "LEFT JOIN vodum_users u ON u.id=a.vodum_user_id "
        "WHERE e.event_type='media_requested' AND e.created_at>=? "
        "ORDER BY e.created_at DESC,e.id DESC", (start,)):
        row = dict(source)
        try: details = json.loads(row.pop('details_json') or '{}')
        except (ValueError,TypeError): details = {}
        if not isinstance(details,dict): details = {}
        result = details.get('request_result') or ''
        request_counts['total'] += 1
        category = {'portal_requests_added':'added', 'portal_requests_present':'present',
                    'portal_requests_pending':'pending'}.get(result)
        if category: request_counts[category] += 1
        elif row['outcome'] != 'success': request_counts['failed'] += 1
        if len(media_requests) < 100:
            media_requests.append({**row, 'title':details.get('media_title') or '—',
                                  'kind':details.get('media_kind'), 'result':result})
    return {'request_counts':request_counts, 'media_requests':media_requests,
            'stats': stats, 'timeline': timeline, 'users': users, 'events': events,
            'days': days, 'page': page, 'pages': pages, 'total_events': count}
