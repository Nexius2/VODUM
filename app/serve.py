"""Production server with an HTTP-verified readiness announcement."""
import os
import threading
import time
from contextvars import ContextVar
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def announce_when_ready(port, started_at, stopped, *, opener=None, emit=print):
    # Readiness is local and must not use an HTTP proxy configured for providers.
    opener = opener or build_opener(ProxyHandler({}))
    while not stopped.is_set():
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    emit(f"VODUM READY — Application started and ready to accept connections on port {port} "
                         f"(startup: {time.time()-started_at:.1f}s).", flush=True)
                    return
        except (URLError, OSError):
            pass
        stopped.wait(0.25)


def create_web_server(application, *, threads, measure_queue=False, **settings):
    from waitress import create_server

    if not measure_queue:
        return create_server(application, threads=threads, **settings)

    from waitress.task import ThreadedTaskDispatcher

    queue_wait_us = ContextVar("waitress_queue_wait_us", default=None)

    class MeasuredTask:
        def __init__(self, task):
            self.task = task
            self.submitted_at = time.perf_counter_ns()

        def service(self):
            token = queue_wait_us.set((time.perf_counter_ns() - self.submitted_at) // 1000)
            try:
                self.task.service()
            finally:
                queue_wait_us.reset(token)

        def cancel(self):
            self.task.cancel()

    class MeasuringDispatcher(ThreadedTaskDispatcher):
        def add_task(self, task):
            super().add_task(MeasuredTask(task))

    def measured_application(environ, start_response):
        environ["vodum.waitress_queue_wait_us"] = queue_wait_us.get()
        return application(environ, start_response)

    # Waitress 3.0.2 accepts a dispatcher at server creation. Start its workers
    # only after the listen socket was successfully opened.
    dispatcher = MeasuringDispatcher()
    server = create_server(measured_application, _dispatcher=dispatcher, threads=threads, **settings)
    dispatcher.set_thread_count(threads)
    return server


def main():
    started_at = float(os.environ.get('VODUM_STARTUP_STARTED_AT') or time.time())
    print('VODUM startup: loading application and background services...', flush=True)
    from run import app
    port = int(os.environ.get('VODUM_PORT', '5000'))
    server = create_web_server(app, host='0.0.0.0', port=port,
        measure_queue=os.environ.get("VODUM_WAITRESS_QUEUE_TIMING") == "1",
        threads=int(os.environ.get('VODUM_WAITRESS_THREADS', '6')),
        max_request_body_size=int(os.environ.get('VODUM_MAX_UPLOAD_MB', '4096'))*1024*1024)
    stopped = threading.Event()
    threading.Thread(target=announce_when_ready, args=(port, started_at, stopped),
                     name='vodum-readiness', daemon=True).start()
    try:
        server.run()
    finally:
        stopped.set()
        server.close()


if __name__ == '__main__':
    main()
