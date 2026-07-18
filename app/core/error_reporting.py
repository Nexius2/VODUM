import threading


_thread_hook_lock = threading.Lock()
_thread_hook_installed = False


def register_flask_exception_logging(app, logger):
    """Log exceptions that escape Flask request handling into VODUM's log."""
    from flask import got_request_exception, request

    def log_unhandled_request(sender, exception, **extra):
        logger.error(
            "Unhandled request exception | method=%s | path=%s | endpoint=%s",
            request.method,
            request.path,
            request.endpoint or "-",
            exc_info=(type(exception), exception, exception.__traceback__),
        )

    got_request_exception.connect(log_unhandled_request, app, weak=False)
    app.extensions["vodum_exception_logger"] = log_unhandled_request


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
