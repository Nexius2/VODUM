import json
import threading
import time
import websocket

from logging_utils import get_logger
from db_manager import DBManager
from config import Config

logger = get_logger("plex.websocket")


class PlexWebsocketClient:

    def __init__(self, server):
        self.server = server
        self.ws = None
        self.db = DBManager(Config.DATABASE_PATH)
        self.last_refresh_ts = 0
        self._refresh_lock = threading.Lock()

    def start(self):
        thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"plex-ws-{self.server['id']}"
        )
        thread.start()

    def _run(self):
        while True:
            try:
                self._connect()
            except Exception as e:
                logger.warning(
                    f"Plex websocket disconnected for server "
                    f"{self.server['name']}: {e}"
                )

            time.sleep(10)

    def _bootstrap_existing_sessions(self):
        self._refresh_live_sessions()

    def _candidate_bases(self):
        bases = []
        invalid_literals = {"", "none", "null", "undefined"}

        for key in ("url", "local_url", "public_url"):
            raw = self.server.get(key)
            if not raw:
                continue

            base = str(raw).strip().rstrip("/")
            if base.lower() in invalid_literals:
                continue
            if not (base.startswith("http://") or base.startswith("https://")):
                continue
            if base not in bases:
                bases.append(base)

        return bases

    def _connect(self):
        token = self.server.get("token")
        if not token:
            return

        ws_errors = []
        for base_url in self._candidate_bases():
            ws_url = (
                base_url
                .replace("https://", "wss://")
                .replace("http://", "ws://")
            )
            ws_url += f"/:/websockets/notifications?X-Plex-Token={token}"

            logger.info(f"Connecting Plex websocket: {self.server['name']} via {base_url}")

            try:
                self.ws = websocket.create_connection(ws_url, timeout=30)
                break
            except Exception as e:
                ws_errors.append(f"{base_url}: {e}")
                logger.debug(
                    f"Plex websocket unavailable for "
                    f"{self.server['name']} via {base_url}: {e}"
                )

        if not self.ws:
            if ws_errors:
                logger.debug(
                    f"Plex websocket unavailable for {self.server['name']} on all URLs: "
                    + " | ".join(ws_errors)
                )
            return

        logger.info(f"Plex websocket connected: {self.server['name']}")
        self._bootstrap_existing_sessions()

        while True:
            raw = self.ws.recv()
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            self._handle_event(data)

    def _refresh_live_sessions(self):
        if not self._refresh_lock.acquire(blocking=False):
            return

        try:
            from core.monitoring.collector import collect_sessions_for_server

            report = collect_sessions_for_server(
                self.db,
                int(self.server["id"]),
                provider="plex",
            )
            self._enqueue_stream_enforcer_if_live(report)

            logger.info(
                f"Refreshed {report.get('sessions_seen', 0)} live sessions "
                f"for {self.server['name']}"
            )

        except Exception:
            logger.exception(
                f"Unable to refresh live sessions for {self.server['name']}"
            )
        finally:
            self._refresh_lock.release()

    def _enqueue_stream_enforcer_if_live(self, report: dict):
        try:
            if int((report or {}).get("sessions_seen") or 0) <= 0:
                return

            row = self.db.query_one("""
                SELECT id, enabled, status, queued_count
                FROM tasks
                WHERE name = 'stream_enforcer'
                LIMIT 1
            """)
            if not row or not int(row["enabled"] or 0):
                return
            if str(row["status"] or "").lower() == "running" or int(row["queued_count"] or 0) > 0:
                return

            from tasks_engine import enqueue_task
            enqueue_task(int(row["id"]))
        except Exception:
            logger.debug("Unable to enqueue stream_enforcer after Plex websocket refresh", exc_info=True)

    def _event_details(self, data: dict) -> tuple[str, set[str]]:
        container = data.get("NotificationContainer") if isinstance(data, dict) else None
        payload = container if isinstance(container, dict) else data

        event_type = str((payload or {}).get("type") or "").strip().lower()
        states = set()

        if isinstance(payload, dict):
            for key in ("PlaySessionStateNotification", "TimelineEntry", "ActivityNotification"):
                items = payload.get(key) or []
                if isinstance(items, dict):
                    items = [items]
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    state = str(item.get("state") or item.get("event") or "").strip().lower()
                    if state:
                        states.add(state)

        return event_type, states

    def _handle_event(self, data):
        try:
            event_type, states = self._event_details(data)

            if event_type not in {"playing", "timeline"} and not (states & {"playing", "paused", "stopped", "buffering"}):
                return

            now = time.time()
            if now - self.last_refresh_ts < 1.0:
                return

            self.last_refresh_ts = now
            self._refresh_live_sessions()

        except Exception:
            logger.exception("Unable to process websocket event")