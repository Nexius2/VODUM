from core.providers.registry import get_provider
import json
import time
from core import stream_kill_diagnostics as diagnostics
from logging_utils import get_logger

logger = get_logger('stream_enforcer')


def kill_session(server_row: dict, session_key: str, reason: str) -> bool:
    report = diagnostics.begin(server_row.get('id'), session_key, server_row.get('type'))
    started = time.monotonic()
    try:
        ok = get_provider(server_row).terminate_session(session_key, reason=reason)
        if report['outcome'] == 'started':
            report['outcome'] = 'provider_reported_stopped' if ok else 'provider_reported_failure'
        report['success'] = bool(ok)
        return ok
    except Exception as exc:
        report.update(outcome='exception', success=False, **diagnostics.exception_fields(exc))
        raise
    finally:
        report['duration_ms'] = round((time.monotonic() - started) * 1000)
        diagnostics.analyze(report)
        (logger.info if report.get('success') else logger.warning)(
            'Stream termination diagnostic | %s', json.dumps(report, ensure_ascii=True))


def warn_session(server_row: dict, session_key: str, title: str, text: str, timeout_ms: int = 8000):
    provider = get_provider(server_row)
    try:
        return provider.send_session_message(session_key, title, text, timeout_ms=timeout_ms)
    except TypeError:
        return provider.send_session_message(session_key, title, text)
