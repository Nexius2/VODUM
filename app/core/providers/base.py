from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ServerConfig:
    id: int
    type: str              # 'plex' | 'jellyfin'
    url: Optional[str]
    local_url: Optional[str]
    public_url: Optional[str]
    token: Optional[str]
    server_identifier: str
    settings_json: Optional[str]


class BaseProvider:
    provider_name: str  # 'plex' | 'jellyfin'

    def __init__(self, server: ServerConfig, timeout: int = 8) -> None:
        self.server = server
        self.timeout = timeout

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """
        Retourne une liste de sessions NORMALISÉES (format Vodum),
        pas le raw du provider.
        """
        raise NotImplementedError


    def send_session_message(self, session_key: str, title: str, text: str, timeout_ms: int = 8000) -> bool:
        return False

    def terminate_session(self, session_key: str, reason: str = "") -> bool:
        raise NotImplementedError
