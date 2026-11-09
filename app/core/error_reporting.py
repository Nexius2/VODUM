import threading
import json
import sys
import traceback
import re
import time
import uuid
from contextlib import contextmanager


@contextmanager
def request_phase(name):
    from flask import g, has_request_context
    started = time.monotonic()
    try:
        yield
    finally:
        if has_request_context():
            if not hasattr(g, 'request_phase_ms'):
                g.request_phase_ms = {}
            g.request_phase_ms[name] = round((time.monotonic() - started) * 1000)


def log_handled_failure(operation, *, level="warning", context=None, **identifiers):
    """Report a recovered failure without logging provider credentials or payloads.

    Call inside an except block. Exception messages can contain unlabelled
    passwords, so retain the exception type and stack locations, not its value.
    Numeric identifiers and explicitly allowed object names identify the failure.
    Never pass URLs, secrets or external exception messages.
    The lazy import also allows bootstrap modules to use this helper.
    """
    from logging_utils import get_logger

    exc_type, _, tb = sys.exc_info()
    numeric_context = " ".join(
        f"{key}={value}" for key, value in identifiers.items()
        if isinstance(value, int) and not isinstance(value, bool)
    )
    allowed={'collection_name','library_name','server_name','object_title','instance_id'}
    details={key:value[:200] for key,value in (context or {}).items() if key in allowed and isinstance(value,str)}
    details.update({key:value for key,value in identifiers.items() if isinstance(value,int) and not isinstance(value,bool)})
    context = numeric_context+' | context='+json.dumps(details,ensure_ascii=False)
    frames = " -> ".join(
        f"{frame.filename}:{frame.lineno} ({frame.name})"
        for frame in traceback.extract_tb(tb)
    ) if tb else "-"
    logger = get_logger("operations")
    getattr(logger, level if level in {"warning", "error"} else "warning")(
        "Operation failed | operation=%s | %s | error_type=%s | stack=%s",
        operation, context, exc_type.__name__ if exc_type else "unknown", frames,
    )


_thread_hook_lock = threading.Lock()
_thread_hook_installed = False


def register_flask_exception_logging(app, logger, *, register_action_hook=True):
    """Log exceptions that escape Flask request handling into VODUM's log."""
    from flask import g, got_request_exception, request, session

    @app.before_request
    def remember_action_messages():
        g.log_existing_flashes = list(session.get("_flashes", []))
        g.request_started_at = time.monotonic()
        supplied = request.headers.get('X-VODUM-Request-ID', '')
        g.diagnostic_request_id = supplied if re.fullmatch('[a-f0-9]{32}', supplied) else uuid.uuid4().hex

    @app.after_request
    def log_request_duration(response):
        finished = time.monotonic()
        elapsed = round((finished - getattr(g, 'request_started_at', finished)) * 1000)
        response.headers['X-VODUM-Request-ID'] = getattr(g, 'diagnostic_request_id', uuid.uuid4().hex)
        if (request.headers.get('HX-Request') == 'true' or request.path.startswith('/dashboard/')) and (elapsed >= 1000 or response.status_code >= 500):
            logger.warning('HTTP request diagnostic | request_id=%s | endpoint=%s | status=%s | duration_ms=%s | phases_ms=%s',
                           response.headers['X-VODUM-Request-ID'], request.endpoint or 'unmatched', response.status_code,
                           elapsed, getattr(g, 'request_phase_ms', {}))
        return response

    def log_unhandled_request(sender, exception, **extra):
        logger.error(
            "Unhandled request exception | method=%s | path=%s | endpoint=%s",
            request.method,
            request.url_rule.rule if request.url_rule else "unmatched",
            request.endpoint or "-",
            exc_info=(type(exception), exception, exception.__traceback__),
        )

    got_request_exception.connect(log_unhandled_request, app, weak=False)
    app.extensions["vodum_exception_logger"] = log_unhandled_request

    client_log_lock = threading.Lock()
    client_log_window = {"start": 0.0, "count": 0}

    @app.post("/api/client-errors")
    @app.post("/api/portal/client-errors")
    def report_client_error():
        # Both URLs inherit the existing admin/portal access and CSRF guards.
        # No free-text error messages, URLs, stack values or form data accepted.
        from flask import abort
        if request.content_length is None or request.content_length > 1024:
            abort(413)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str) or payload.get("kind") not in {
            "javascript", "unhandledrejection", "console_error", "htmx",
        }:
            abort(400)
        with client_log_lock:
            now = time.monotonic()
            if now - client_log_window["start"] >= 60:
                client_log_window.update(start=now, count=0)
            if client_log_window["count"] >= 60:
                return "", 429
            client_log_window["count"] += 1
        source = payload.get("source")
        if not isinstance(source, str) or not re.fullmatch(r"(?:inline|/static/js/[\w/-]+\.js|/static/vendor/htmx/htmx\.min\.js)", source, flags=re.ASCII):
            source = "unknown"
        line = payload.get("line")
        line = line if type(line) is int and 0 <= line <= 1000000 else 0
        page = payload.get('page')
        if not isinstance(page, str) or page not in {
            'dashboard','monitoring','users','servers','collections','subscriptions',
            'communications','migrations','backup','settings','portal','logs','tasks','about',
        }:
            page = 'unknown'
        operation = payload.get('operation')
        if not isinstance(operation, str) or operation not in {
            'refresh','run_task','init_tabs','refresh_tab','collection_refresh',
            'collection_save','collection_queue','collection_settings',
            'htmx_responseError','htmx_sendError','htmx_timeout','htmx_swapError','htmx_targetError',
        }:
            operation = 'unknown'
        status = payload.get('http_status')
        status = status if type(status) is int and 0 <= status <= 599 else 0
        component = payload.get('component')
        if not isinstance(component, str) or component not in {
            'dashboard_now_playing','dashboard_next_tasks','dashboard_subscriptions','dashboard_usage_risk','dashboard_servers',
        }:
            component = 'unknown'
        correlation = payload.get('request_id')
        correlation = correlation if isinstance(correlation,str) and re.fullmatch('[a-f0-9]{32}',correlation) else '-'
        def duration(key):
            value = payload.get(key)
            return value if type(value) is int and 0 <= value <= 3600000 else 0
        if payload['kind'] == 'htmx' and component.startswith('dashboard_'):
            labels = {
                'dashboard_servers': 'Servers (including 7-day stream peaks)',
                'dashboard_now_playing': 'Now playing',
                'dashboard_next_tasks': 'Tasks',
                'dashboard_subscriptions': 'Subscriptions',
                'dashboard_usage_risk': 'Usage risk',
            }
            reasons = {
                'htmx_timeout': 'Browser deadline exceeded; response not received in time (server processing or transport cause not yet established)',
                'htmx_sendError': 'Request transport failed; no usable HTTP response',
                'htmx_responseError': 'Server returned an unsuccessful HTTP response',
                'htmx_swapError': 'Application failed to insert the response into the page',
                'htmx_targetError': 'Application could not find the page element to update',
            }
            if operation in reasons:
                transient = operation in {'htmx_timeout', 'htmx_sendError'}
                log = logger.warning if transient else logger.error
                log("Dashboard refresh failed | widget=%s | reason=%s | impact=Widget was not updated; previously displayed data may be stale | diagnosis=Match request_id with HTTP request diagnostic for server status and phase durations; this is not a media-server availability check | http_status=%s | component=%s | request_id=%s | elapsed_ms=%s | timeout_ms=%s",
                    labels[component], reasons[operation], status, component, correlation,
                    duration('elapsed_ms'), duration('timeout_ms'))
                return "", 204
        logger.error("Browser error | kind=%s | source=%s | line=%s | page=%s | operation=%s | http_status=%s | component=%s | request_id=%s | elapsed_ms=%s | timeout_ms=%s",
                     payload['kind'], source, line, page, operation, status, component, correlation,
                     duration('elapsed_ms'), duration('timeout_ms'))
        return "", 204

    def log_action_result(response):
        if request.endpoint == "report_client_error":
            return response  # The bounded browser report above is already logged.
        # Endpoint names avoid leaking activation tokens and other path values.
        # Do not inspect request bodies, cookies, headers or query strings.
        action = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        existing = list(getattr(g, "log_existing_flashes", []))
        new_categories = []
        for item in session.get("_flashes", []):
            if item in existing:
                existing.remove(item)
            else:
                new_categories.append(item[0])
        flashed_failure = any(category in {"error", "danger", "warning"} for category in new_categories)
        failed = response.status_code >= 400 or flashed_failure
        # File responses may be sized (not streamed) but still forbid body reads.
        if not response.direct_passthrough and not response.is_streamed and response.is_json:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict):
                failed = (
                    failed or payload.get("ok") is False or payload.get("success") is False
                    or bool(payload.get("error")) or bool(payload.get("errors"))
                    or payload.get("status") in ("error", "failed")
                )
        if not action and not failed:
            return response
        log = logger.error if response.status_code >= 500 else logger.warning if failed else logger.info
        targets = " ".join(
            f"{key}={value}" for key, value in (request.view_args or {}).items()
            if type(value) is int
        ) or "-"
        log(
            "HTTP action result | method=%s | endpoint=%s | status=%s | outcome=%s | targets=%s",
            request.method, request.endpoint or "unmatched", response.status_code,
            "failed" if failed else "completed", targets,
        )
        return response

    app.extensions["vodum_action_logger"] = log_action_result
    if register_action_hook:
        app.after_request(log_action_result)


def install_thread_exception_logging(logger):
    """Install one process-wide hook for exceptions escaping Python threads."""
    global _thread_hook_installed

    with _thread_hook_lock:
        if _thread_hook_installed:
            return False

        previous_hook = threading.excepthook

        def log_unhandled_thread(args):
            if args.exc_type is SystemExit:
                previous_hook(args)
                return
            logger.error(
                "Unhandled thread exception | thread=%s",
                args.thread.name if args.thread else "unknown",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = log_unhandled_thread
        _thread_hook_installed = True
        return True
