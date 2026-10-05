"""Read-only, aggregate diagnostics for the subscription detection pipeline.

Run inside the VODUM container: python /app/diagnose_stream_policies.py /appdata/database.db
No provider calls, bootstrap, messages, or playback actions are performed.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def diagnose(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only = ON')
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'errors': {}}

    def check(name, sql, params=()):
        try:
            report['checks'][name] = [dict(row) for row in connection.execute(sql, params)]
        except sqlite3.Error as exc:
            report['errors'][name] = str(exc)

    try:
        check('settings', '''SELECT enable_cron_jobs, usage_risk_enabled,
            usage_risk_send_upgrade_suggestions, usage_risk_min_kills_before_suggestion,
            usage_risk_analysis_window_days, usage_risk_medium_threshold,
            usage_risk_high_threshold FROM settings WHERE id=1''')
        check('tasks', '''SELECT name, enabled, status, schedule_mode, interval_seconds,
            queued_count, last_run, CASE WHEN COALESCE(last_error, '') <> '' THEN 1 ELSE 0 END AS has_error
            FROM tasks WHERE name IN ('monitor_enqueue_refresh', 'media_jobs_worker',
            'stream_enforcer', 'usage_risk_notifications')''')
        check('servers', '''SELECT id, LOWER(TRIM(type)) AS provider, status,
            cooldown_until, last_checked FROM servers WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')''')
        check('refresh_jobs', '''SELECT server_id, status, COUNT(*) AS count,
            MAX(processed_at) AS last_processed_at, MIN(created_at) AS oldest_created_at
            FROM media_jobs WHERE action='refresh' GROUP BY server_id, status''')
        check('sessions', '''SELECT ms.server_id, COUNT(*) AS stored,
            MAX(ms.last_seen_at) AS last_seen_at,
            SUM(CASE WHEN datetime(ms.last_seen_at) >= datetime('now','-90 seconds')
                AND COALESCE(ms.missing_count,0)=0 THEN 1 ELSE 0 END) AS fresh_present,
            SUM(CASE WHEN datetime(ms.last_seen_at) >= datetime('now','-90 seconds')
                AND COALESCE(ms.missing_count,0)=0 AND mu.vodum_user_id IS NULL THEN 1 ELSE 0 END) AS fresh_unmapped,
            SUM(CASE WHEN datetime(ms.last_seen_at) >= datetime('now','-90 seconds')
                AND COALESCE(ms.missing_count,0)=0 AND TRIM(COALESCE(ms.ip,'')) IN ('','unknown') THEN 1 ELSE 0 END) AS fresh_missing_ip
            FROM media_sessions ms LEFT JOIN media_users mu ON mu.id=ms.media_user_id GROUP BY ms.server_id''')
        check('policy_counts', '''SELECT is_enabled, scope_type, rule_type, COUNT(*) AS count
            FROM stream_policies GROUP BY is_enabled, scope_type, rule_type''')
        check('user_overrides', '''SELECT COUNT(*) AS users_with_positive_override
            FROM vodum_users WHERE max_streams_override > 0''')
        check('linked_accounts', '''SELECT COUNT(*) AS users_with_multiple_external_ids FROM
            (SELECT vodum_user_id FROM media_users WHERE vodum_user_id IS NOT NULL
             GROUP BY vodum_user_id HAVING COUNT(DISTINCT external_user_id)>1)''')
        check('enforcements_30d', '''SELECT date(created_at) AS day, action, COUNT(*) AS count
            FROM stream_enforcements WHERE datetime(created_at)>=datetime('now','-30 days')
            GROUP BY date(created_at), action ORDER BY day''')
        invalid = []
        try:
            for row in connection.execute('SELECT id, rule_type, rule_value_json FROM stream_policies WHERE is_enabled=1'):
                try:
                    value = json.loads(row['rule_value_json'] or '{}')
                    if not isinstance(value, dict):
                        raise ValueError('rule must be an object')
                    if row['rule_type'] in {'max_streams_per_user', 'max_streams_per_ip', 'max_ips_per_user', 'max_transcodes_global'}:
                        if int(value.get('max', 1)) < 0:
                            raise ValueError('negative max')
                except (ValueError, TypeError, OverflowError):
                    invalid.append({'id': row['id'], 'rule_type': row['rule_type']})
            report['checks']['invalid_enabled_policies'] = invalid
        except sqlite3.Error as exc:
            report['errors']['invalid_enabled_policies'] = str(exc)
        return report
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='Existing VODUM SQLite database path')
    args = parser.parse_args()
    try:
        report = diagnose(args.database)
    except (sqlite3.Error, OSError) as exc:
        parser.exit(1, f'Unable to read database: {exc}\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
