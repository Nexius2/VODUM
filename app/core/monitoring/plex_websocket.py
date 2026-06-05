import json
import threading
import time
import websocket

from logging_utils import get_logger
from db_manager import DBManager
from config import Config


from core.providers.registry import get_provider
logger = get_logger("plex.websocket")


class PlexWebsocketClient:

    def __init__(self, server):
        self.server = server
        self.ws = None
        self.db = DBManager(Config.DATABASE_PATH)
        self.last_refresh_ts = 0

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

            time.sleep(60)

    def _bootstrap_existing_sessions(self):

        self._refresh_live_sessions()

    def _connect(self):

        base_url = (
            self.server.get("url")
            or self.server.get("local_url")
            or self.server.get("public_url")
        )

        if not base_url:
            return

        base_url = base_url.rstrip("/")

        token = self.server.get("token")

        if not token:
            return

        ws_url = (
            base_url
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )

        ws_url += f"/:/websockets/notifications?X-Plex-Token={token}"

        logger.info(f"Connecting Plex websocket: {self.server['name']}")

        try:

            self.ws = websocket.create_connection(
                ws_url,
                timeout=30
            )

        except Exception as e:

            logger.debug(
                f"Plex websocket unavailable for "
                f"{self.server['name']}: {e}"
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

        try:
            from core.monitoring.collector import collect_sessions_for_server

            report = collect_sessions_for_server(
                self.db,
                int(self.server["id"]),
                provider="plex",
            )

            logger.info(
                f"Refreshed {report.get('sessions_seen', 0)} live sessions "
                f"for {self.server['name']}"
            )

        except Exception:
            logger.exception(
                f"Unable to refresh live sessions for {self.server['name']}"
            )

    def _handle_event(self, data):

        try:

            event_type = str(data.get("type") or "").lower()

            if event_type != "playing":
                return

            now = time.time()

            if now - self.last_refresh_ts < 5:
                return

            self.last_refresh_ts = now

            self._refresh_live_sessions()

        except Exception:
            logger.exception("Unable to process websocket event")