import threading
import sys
import traceback
import re
import time


def log_handled_failure(operation, *, level="warning", **identifiers):
    """Report a recovered failure without logging provider credentials or payloads.

    Call inside an except block. Exception messages can contain unlabelled
    passwords, so retain the exception type and stack locations, not its value.
    Only pass numeric internal IDs as context; never pass URLs or user input.
    The lazy import also allows bootstrap modules to use this helper.
    """
    from logging_utils import get_logger

    exc_type, _, tb = sys.exc_info()
    context = " ".join(
        f"{key}={value}" for key, value in identifiers.items()
        if isinstance(value, int) and not isinstance(value, bool)
    )
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
            "javascript", "unhandledrejection", "console_error",
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
        if not isinstance(source, str) or not re.fullmatch(r"/static/js/[\w/-]+\.js", source, flags=re.ASCII):
            source = "unknown"
        line = payload.get("line")
        line = line if type(line) is int and 0 <= line <= 1000000 else 0
        logger.error("Browser error | kind=%s | source=%s | line=%s", payload["kind"], source, line)
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
        if response.is_json and not response.is_streamed:
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
