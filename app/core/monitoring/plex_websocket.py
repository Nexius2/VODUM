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

            except Exception:
                logger.exception(
                    f"Plex websocket crashed for server {self.server['name']}"
                )

            time.sleep(10)

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

        self.ws = websocket.create_connection(
            ws_url,
            timeout=30
        )

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

            provider = get_provider(dict(self.server))

            live_sessions = provider.get_live_sessions()

            from core.monitoring.collector import (
                persist_live_sessions,
            )

            persist_live_sessions(
                self.db,
                dict(self.server),
                live_sessions,
            )

            logger.info(
                f"Refreshed {len(live_sessions or [])} live sessions "
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