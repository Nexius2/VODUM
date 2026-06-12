"""Validate artwork provider fetching and enforce the route/service boundary."""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")

    class RequestsSession:
        def __init__(self):
            self.verify = True

        def get_redirect_target(self, response):
            return None

    requests_stub.Session = RequestsSession
    requests_stub.exceptions = types.SimpleNamespace(InvalidURL=ValueError)
    sys.modules["requests"] = requests_stub

from core.monitoring import artwork_cache, artwork_proxy  # noqa: E402


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


class Response:
    content = PNG
    headers = {"Content-Type": "image/png"}

    def raise_for_status(self):
        return None


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        artwork_cache.ARTWORK_CACHE_DIR = Path(tmp)
        session = Session()
        artwork_proxy.server_http_session = lambda server: session
        artwork_proxy.wait_for_plex_slot = lambda base: None

        plex = {"id": 1, "type": "plex", "url": "http://plex", "token": "token"}
        result = artwork_proxy.fetch_monitoring_artwork(plex, {"path": "/library/metadata/1/thumb"})
        assert result["kind"] == "content" and result["content"] == PNG
        assert session.calls[0][1]["headers"] == {"X-Plex-Token": "token"}

        jellyfin = {"id": 2, "type": "jellyfin", "url": "http://jellyfin", "token": "key"}
        result = artwork_proxy.fetch_monitoring_artwork(jellyfin, {"item_id": "abc"})
        assert result["kind"] == "content"
        assert session.calls[-1][1]["headers"] == {"X-Emby-Token": "key"}

        try:
            artwork_proxy.fetch_monitoring_artwork(plex, {"path": "https://external/image"})
        except artwork_proxy.ArtworkProxyError as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Unsafe Plex artwork path was accepted")

    route = (ROOT / "app" / "routes" / "monitoring_api.py").read_text(encoding="utf-8")
    for forbidden in ("server_http_session", "X-Plex-Token", "X-Emby-Token", "wait_for_plex_slot"):
        assert forbidden not in route, f"Provider detail remains in monitoring route: {forbidden}"
    assert "fetch_monitoring_artwork" in route
    print("OK - artwork provider fetching is isolated from the monitoring route.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
