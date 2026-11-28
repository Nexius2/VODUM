"""Per-attempt diagnostics; no URLs, tokens, response bodies or exception text."""
import json
import uuid
from contextvars import ContextVar

_current = ContextVar('stream_kill_diagnostic', default=None)


def begin(server_id, session_key, provider):
    report = {'attempt_id': uuid.uuid4().hex, 'server_id': server_id,
              'session_key': str(session_key), 'provider': provider,
              'outcome': 'started', 'events': []}
    _current.set(report)
    return report


def event(stage, **fields):
    report = _current.get()
    if report is not None and len(report['events']) < 100:
        report['events'].append({'stage': stage, **fields})
        if stage == 'result':
            report['outcome'] = fields['outcome']


def exception_fields(exc):
    cause = exc
    seen = set()
    status = None
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        code = getattr(getattr(cause, 'response', None), 'status_code', None)
        if type(code) is int:
            status = code
        last_type = type(cause).__name__
        cause = cause.__cause__
    return {'error_type': type(exc).__name__, 'cause_type': last_type,
            'http_status': status}


def take(server_id, session_key):
    report = _current.get()
    _current.set(None)
    if report and report['server_id'] == server_id and report['session_key'] == str(session_key):
        return report
    return None


def merge(details_json, server_id, session_key):
    report = take(server_id, session_key)
    if not report:
        return details_json
    details = json.loads(details_json or '{}')
    details['termination'] = report
    return json.dumps(details, ensure_ascii=False)


def analyze(report):
    """Describe observations, without claiming that a paused client is stopped."""
    checks = [item for item in report['events'] if item['stage'] == 'verification']
    present = [item for item in checks if item.get('session_id') is not None]
    progress = []
    for item in present:
        try:
            progress.append(int(item['progress_ms']))
        except (KeyError, TypeError, ValueError):
            pass
    report['analysis'] = {
        'verification_count': len(checks),
        'session_recreated': any(item['stage'] == 'session_recreated' for item in report['events']),
        'last_observed_state': present[-1].get('state') if present else None,
        'progress_increased': any(b > a for a, b in zip(progress, progress[1:])),
        'http_statuses': sorted({item['http_status'] for item in report['events']
                                 if type(item.get('http_status')) is int}),
    }
    if report.get('outcome') == 'exception':
        report['analysis']['failure_category'] = (
            'http_error' if report.get('http_status') is not None else
            'timeout' if report.get('cause_type') in ('Timeout', 'ReadTimeout', 'ConnectTimeout') else
            'connection_error' if report.get('cause_type') == 'ConnectionError' else
            'provider_exception'
        )
    else:
        report['analysis']['failure_category'] = None if report.get('success') else report['outcome']
