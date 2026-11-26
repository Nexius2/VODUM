"""Normalized, persisted historical tab views; live overlays stay on HTTP reads."""

import hashlib
import json

from werkzeug.datastructures import MultiDict
from db_manager import isolated_read_operation

RANGES = {'7d', '1m', '6m', '12m', 'all'}


def normalize(kind, args=None, cookies=None):
    args = MultiDict(args or {})
    cookies = cookies or {}
    if kind == 'history':
        from core.monitoring.overview_history import HISTORY_SORT_COLUMNS
        sort = (args.get('sort') or cookies.get('monitoring_history_sort', 'date')).strip()
        direction = (args.get('dir') or cookies.get('monitoring_history_dir', 'desc')).strip().lower()
        return dict(page=max(1, args.get('page', 1, type=int)),
                    sort=sort if sort in HISTORY_SORT_COLUMNS else 'date',
                    dir=direction if direction in {'asc', 'desc'} else 'desc',
                    q=args.get('q', '').strip(), provider=args.get('provider', '').strip(),
                    media_type=args.get('media_type', '').strip(), playback=args.get('playback', '').strip(),
                    server=args.get('server', type=int))
    if kind == 'users':
        from core.monitoring.overview_users import build_monitoring_users_options
        options = build_monitoring_users_options(args, cookies)
        return dict(page=max(1, options['page']), q=options['q'], sort=options['sort_key'], dir=options['sort_dir'])
    if kind in {'servers', 'activity', 'user_daily'}:
        ranges = {'7d', '30d', '90d', '12m', 'all'} if kind == 'user_daily' else RANGES
        fallback = '30d' if kind == 'user_daily' else '7d'
        options = {'range': args.get('range') if args.get('range') in ranges else fallback}
        if kind == 'user_daily':
            options['user_id'] = args.get('user_id', 0, type=int)
        return options
    if kind == 'policies':
        size = args.get('enforcement_per_page', 20, type=int)
        return dict(enforcement_page=max(1, args.get('enforcement_page', 1, type=int)),
                    enforcement_per_page=size if size in {20, 50, 100} else 20)
    if kind == 'usage_risk':
        from core.monitoring.overview_usage_risk import build_usage_risk_filters
        return build_usage_risk_filters(args)
    if kind == 'user_portal':
        days = args.get('days', 30, type=int)
        return dict(days=days if days in {7, 30, 90} else 30, page=max(1, args.get('page', 1, type=int)))
    if kind == 'location':
        return dict(server_id=args.get('server_id', type=int), instant=args.get('instant', type=int))
    raise ValueError('Unknown historical monitoring tab')


def view_key(kind, options):
    digest = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()[:24]
    return f'tab:{kind}:{digest}'


def default_views():
    return tuple((view_key(kind, normalize(kind)), 'tab_' + kind, normalize(kind)) for kind in
                 ('history', 'users', 'servers', 'activity', 'policies', 'usage_risk', 'user_portal', 'location'))


def load_tab_snapshot(db, kind, args=None, cookies=None):
    from core.monitoring.precomputed import load_snapshot
    options = normalize(kind, args, cookies)
    return load_snapshot(db, view_key(kind, options), 'tab_' + kind, options)


def compute_tab(db, kind, options):
    args = MultiDict(options)
    if kind == 'history':
        from core.monitoring.overview_history import load_monitoring_history
        return load_monitoring_history(db, args, {}, lambda page: page)
    if kind == 'users':
        from core.monitoring.overview_users import build_monitoring_users_options, load_monitoring_users_total, load_monitoring_users_rows
        return dict(total_rows=load_monitoring_users_total(db, options['q']),
                    rows=load_monitoring_users_rows(db, build_monitoring_users_options(args, {})))
    if kind == 'servers':
        from core.monitoring.overview_servers import load_monitoring_servers_tab
        from core.arr_monitoring import load_arr_monitoring
        from core.arr_connections import load_arr_servers
        result = load_monitoring_servers_tab(db, args, '-300 seconds', {}, include_live=False)
        result['arr_monitoring'] = load_arr_monitoring(db, load_arr_servers(db), options['range'])
        return result
    if kind in {'activity', 'user_daily'}:
        from core.monitoring import activity_statistics as charts
        metrics = ('user_daily',) if kind == 'user_daily' else ('activity', 'media_types', 'per_server', 'weekday')
        return {name: getattr(charts, 'load_' + name)(db, options['range'], options.get('user_id')) for name in metrics}
    if kind == 'policies':
        from core.monitoring import overview_policies as policies
        pagination = policies.load_policy_enforcement_pagination(db, args)
        result = dict(policy_dashboard=policies.load_policy_dashboard(db, policies.load_policy_catalog(db)),
                      policy_top_users_30d=policies.load_policy_top_users(db),
                      policy_recent_enforcements=[dict(row) for row in policies.load_recent_policy_enforcements(db, pagination)],
                      policy_grouped_enforcements=policies.load_grouped_policy_enforcements(db),
                      policy_hits_30d=policies.load_policy_hits_timeline(db))
        result.update(policies.load_policy_breakdowns(db))
        result.update({f'policy_enforcement_{key}': pagination[key] for key in ('page', 'per_page', 'total', 'total_pages')})
        return result
    if kind == 'usage_risk':
        from core.monitoring.overview_usage_risk import load_usage_risk_context
        return load_usage_risk_context(db, args)
    if kind == 'user_portal':
        from core.monitoring.portal_usage import load_portal_usage
        return load_portal_usage(db, options['days'], options['page'], include_live=False)
    if kind == 'location':
        from core.monitoring.overview_locations import _load_playbacks
        return [dict(row) for row in _load_playbacks(db, False, 300, options['server_id'], options['instant'], source='history')]
    raise ValueError('Unknown historical monitoring tab builder')


@isolated_read_operation
def overlay_server_live(db, result, window, resources):
    from core.monitoring.resource_stats import apply_server_resource_stats
    current = {row['server_id']: dict(row) for row in db.query('''
        SELECT s.id AS server_id,s.name,LOWER(TRIM(COALESCE(s.status,'unknown'))) AS status,s.last_checked,
          COUNT(ms.id) AS live_sessions,COALESCE(SUM(ms.is_transcode=1),0) AS live_transcodes,
          COALESCE(SUM(ms.id IS NOT NULL AND COALESCE(ms.is_transcode,0)=0),0) AS live_direct_plays
        FROM servers s LEFT JOIN media_sessions ms ON ms.server_id=s.id
          AND datetime(ms.last_seen_at)>=datetime('now',?)
        WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin') GROUP BY s.id
    ''', (window,))}
    result['live_servers'] = list(current.values())
    result['servers_details'] = [dict(row, **{k: v for k, v in current[row['server_id']].items() if k != 'server_id'})
                                for row in result['servers_details'] if row['server_id'] in current]
    apply_server_resource_stats(result['servers_details'], resources)
    arr = {r['id']: dict(r) for r in db.query("SELECT id,status,last_checked,server_version FROM servers WHERE LOWER(TRIM(type)) IN ('sonarr','radarr')")}
    for row in result['arr_monitoring']['servers']:
        if row['id'] in arr:
            row.update(arr[row['id']])
            latest = db.query_one('SELECT queue_count,health_count FROM arr_monitoring_samples WHERE server_id=? ORDER BY checked_at DESC,id DESC LIMIT 1', (row['id'],))
            if latest:
                row.update(dict(latest))
    return result


@isolated_read_operation
def portal_online(db):
    row = db.query_one("SELECT COUNT(DISTINCT portal_account_id) n FROM portal_sessions WHERE revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP AND last_seen_at>=datetime('now','-5 minutes')")
    return int(row['n'] or 0)


def load_location_view(db, *, live_only, live_window_seconds, server_id=None, instant=None, playing_only=False, country=""):
    from datetime import datetime, timezone
    from core.monitoring.overview_locations import _load_playbacks, load_monitoring_locations
    if instant is None and (live_only or playing_only):
        return load_monitoring_locations(db, live_only=live_only, live_window_seconds=live_window_seconds,
            server_id=server_id, instant=instant, playing_only=playing_only, country=country), None
    historical, metadata = load_tab_snapshot(db, 'location', dict(server_id=server_id, instant=instant))
    current = [dict(row) for row in _load_playbacks(db, False, live_window_seconds, server_id, instant, source='current')]
    grouped = {}
    def rank(row):
        try:
            stamp = datetime.fromisoformat(row['seen_at'])
            timestamp = (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, TypeError):
            timestamp = float('-inf')
        return timestamp, row['current'], row['id']
    for row in (historical or []) + current:
        previous = grouped.get(row['identity'])
        if previous is None:
            grouped[row['identity']] = dict(row)
        else:
            winner = dict(max((previous, row), key=rank))
            winner.update(online=max(previous['online'], row['online']),
                          active=previous['active'] + row['active'], sessions=previous['sessions'] + row['sessions'])
            grouped[row['identity']] = winner
    rows = sorted(grouped.values(), key=rank, reverse=True)
    return load_monitoring_locations(db, live_only=live_only, live_window_seconds=live_window_seconds,
        server_id=server_id, instant=instant, playing_only=playing_only, country=country, prepared_rows=rows), metadata
