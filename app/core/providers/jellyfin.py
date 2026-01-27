from __future__ import annotations
import json
import requests
from typing import Any, Dict, List, Optional

from core.providers.base import BaseProvider


class JellyfinProvider(BaseProvider):
    provider_name = "jellyfin"

    def _candidate_bases(self) -> List[str]:
        # url > local_url > public_url
        bases: List[str] = []
        for u in (getattr(self.server, "url", None),
                  getattr(self.server, "local_url", None),
                  getattr(self.server, "public_url", None)):
            if u and str(u).strip():
                b = str(u).strip().rstrip("/")
                if b not in bases:
                    bases.append(b)
        return bases

    def _get_json(self, path: str) -> Any:
        bases = self._candidate_bases()
        if not bases:
            raise RuntimeError("Jellyfin server URL missing")

        token = getattr(self.server, "token", None)
        if not token:
            raise RuntimeError("Jellyfin API key missing (stored in servers.token)")

        headers = {
            "X-Emby-Token": token,
            "Accept": "application/json",
        }

        last_exc: Optional[Exception] = None
        errors: List[str] = []

        for base in bases:
            url = f"{base}{path}"
            try:
                r = requests.get(url, headers=headers, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                last_exc = e
                code = getattr(getattr(e, "response", None), "status_code", None)
                errors.append(f"{url} -> {code or type(e).__name__}")
                continue

        raise RuntimeError(f"Jellyfin unreachable via any URL. Attempts: {', '.join(errors)}") from last_exc

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        data = self._get_json("/Sessions")
        sessions: List[Dict[str, Any]] = []

        for s in data or []:
            session_id = s.get("Id")
            user_id = s.get("UserId") or (s.get("User") or {}).get("Id")
            now_playing = s.get("NowPlayingItem") or {}
            item_id = now_playing.get("Id")

            play_state = s.get("PlayState") or {}
            play_method = play_state.get("PlayMethod")
            is_transcode = 1 if str(play_method).lower() == "transcode" else 0

            transcoding_info = s.get("TranscodingInfo") or {}
            bitrate = transcoding_info.get("Bitrate")

            is_paused = play_state.get("IsPaused")
            state = "paused" if is_paused else ("playing" if now_playing else "unknown")

            progress_ticks = play_state.get("PositionTicks")
            progress_ms = int(progress_ticks / 10_000) if isinstance(progress_ticks, int) else None

            runtime_ticks = now_playing.get("RunTimeTicks")
            duration_ms = int(runtime_ticks / 10_000) if isinstance(runtime_ticks, int) else None

            title = now_playing.get("Name")
            media_type = (now_playing.get("Type") or "unknown").lower()

            client_name = s.get("Client") or s.get("DeviceName")
            client_product = s.get("ApplicationVersion")
            device = s.get("DeviceName")
            ip = (s.get("RemoteEndPoint") or "")

            if not session_id:
                continue

            sessions.append({
                "provider": "jellyfin",
                "session_key": str(session_id),
                "external_user_id": str(user_id) if user_id else None,
                "username": s.get("UserName") or (s.get("User") or {}).get("Name"),
                "media_key": str(item_id) if item_id else None,
                "media_type": media_type,
                "title": title,
                "grandparent_title": None,
                "parent_title": None,
                "state": state,
                "progress_ms": progress_ms,
                "duration_ms": duration_ms,
                "is_transcode": is_transcode,
                "bitrate": int(bitrate) if isinstance(bitrate, int) else None,
                "video_codec": (transcoding_info.get("VideoCodec") or None),
                "audio_codec": (transcoding_info.get("AudioCodec") or None),
                "client_name": client_name,
                "client_product": client_product,
                "device": device,
                "ip": ip,
                "raw_json": json.dumps(s, ensure_ascii=False),
            })

        return sessions
