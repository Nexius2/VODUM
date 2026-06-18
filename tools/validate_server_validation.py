"""Validate provider-neutral media-server validation and wizard boundaries."""

from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

http_security = types.ModuleType("core.http_security")
http_security.plex_server_http_session = lambda _server: None
sys.modules["core.http_security"] = http_security

check_servers = types.ModuleType("tasks.check_servers")
check_servers.jellyfin_get_status = lambda _server, url, token: ("up", "Jellyfin", "jf-id", f"{url}:{token}")
sys.modules["tasks.check_servers"] = check_servers

from core import server_validation  # noqa: E402


class Response:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class Session:
    def get(self, url, **_kwargs):
        if url.endswith("/identity"):
            return Response(200, b'<MediaContainer machineIdentifier="plex-id" version="1.2.3"/>')
        return Response(200, b'<MediaContainer friendlyName="Plex Test"/>')


def main() -> int:
    server_validation.plex_server_http_session = lambda _server: Session()
    server_validation.requests.get = lambda *_args, **_kwargs: Response(
        200,
        b'<user username="plex-owner"/>',
    )
    assert server_validation.validate_media_server("plex", "http://plex", "token") == (
        "up", "Plex Test", "plex-id", "1.2.3",
    )
    jellyfin = server_validation.validate_media_server("jellyfin", "http://jf", "key")
    assert jellyfin[:3] == ("up", "Jellyfin", "jf-id")
    assert server_validation.validate_media_server("other", "http://x", "x")[0] == "down"

    route_text = (ROOT / "app" / "routes" / "setup_wizard.py").read_text(encoding="utf-8")
    assert "validate_media_server" in route_text
    assert "plex_server_http_session" not in route_text
    assert "jellyfin_get_status" not in route_text

    print("OK - setup server validation is provider-neutral and outside the route.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
