"""Production server with an HTTP-verified readiness announcement."""
import os
import threading
import time
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


def main():
    started_at = float(os.environ.get('VODUM_STARTUP_STARTED_AT') or time.time())
    print('VODUM startup: loading application and background services...', flush=True)
    from run import app
    from waitress import create_server
    port = int(os.environ.get('VODUM_PORT', '5000'))
    server = create_server(app, host='0.0.0.0', port=port,
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
