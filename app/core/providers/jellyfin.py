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

        invalid_literals = {"none", "null", "undefined", ""}

        for u in (
            getattr(self.server, "url", None),
            getattr(self.server, "local_url", None),
            getattr(self.server, "public_url", None),
        ):
            if not u:
                continue

            b = str(u).strip().rstrip("/")
            if b.lower() in invalid_literals:
                continue

            # refuse "192.168.1.50:8096" sans schéma
            if not (b.startswith("http://") or b.startswith("https://")):
                continue

            if b not in bases:
                bases.append(b)

        return bases


    def _post_json(self, path: str, payload: Optional[dict] = None) -> bool:
        bases = self._candidate_bases()
        if not bases:
            raise RuntimeError("Jellyfin server URL missing")

        token = getattr(self.server, "token", None)
        if not token:
            raise RuntimeError("Jellyfin API key missing (stored in servers.token)")

        headers = {
            "X-Emby-Token": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        last_exc: Optional[Exception] = None
        errors: List[str] = []

        for base in bases:
            url = f"{base}{path}"
            try:
                r = requests.post(url, headers=headers, json=(payload or {}), timeout=self.timeout)
                r.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                last_exc = e
                code = getattr(getattr(e, "response", None), "status_code", None)
                errors.append(f"{url} -> {code or type(e).__name__}")
                continue

        raise RuntimeError(f"Jellyfin POST failed. Attempts: {', '.join(errors)}") from last_exc


    def send_session_message(self, session_key: str, title: str, text: str, timeout_ms: int = 8000) -> bool:
        session_id = str(session_key).split(":", 1)[0]  # sessionId uniquement
        payload = {
            "Header": title,
            "Text": text,
            "TimeoutMs": int(timeout_ms),
        }
        return self._post_json(f"/Sessions/{session_id}/Message", payload)


    def terminate_session(self, session_key: str, reason: str = "") -> bool:
        session_id = str(session_key).split(":", 1)[0]  # sessionId uniquement
        return self._post_json(f"/Sessions/{session_id}/Playing/Stop", {})



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

        raise RuntimeError(
            f"Jellyfin unreachable via any URL. Attempts: {', '.join(errors)}"
        ) from last_exc

    @staticmethod
    def _ticks_to_ms(ticks: Any) -> Optional[int]:
        # Jellyfin ticks = 10_000 ticks per ms
        if isinstance(ticks, int):
            return int(ticks / 10_000)
        return None

    @staticmethod
    def _to_int(v: Any) -> Optional[int]:
        """
        Jellyfin peut renvoyer des nombres en int, float, ou string ("12345").
        On convertit proprement vers int, sinon None.
        """
        if v is None:
            return None
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            # accepte "12345" ou "12345.0"
            try:
                return int(float(s))
            except Exception:
                return None
        return None


    @staticmethod
    def _pick_ip(session: Dict[str, Any]) -> Optional[str]:
        """
        Jellyfin can expose remote ip depending on config/version and reverse proxy.
        Best-effort extraction.
        """
        ip = (
            session.get("RemoteEndPoint")
            or session.get("RemoteAddress")
            or session.get("RemoteIp")
        )

        # Some setups may put it in AdditionalUsers / etc (rare) -> ignore.

        # If behind reverse-proxy, RemoteEndPoint may be proxy IP.
        # Sometimes Jellyfin includes request headers (not always). Best-effort:
        if not ip:
            headers = session.get("Headers") or session.get("RequestHeaders") or {}
            if isinstance(headers, dict):
                xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
                if isinstance(xff, str) and xff.strip():
                    # Take first IP in XFF chain
                    ip = xff.split(",")[0].strip()

        if isinstance(ip, str):
            ip = ip.strip()
            if not ip:
                return None

            # Sometimes Jellyfin returns "IP:PORT"
            # Example: "192.168.1.12:51234"
            if ":" in ip and ip.count(":") == 1:
                host, port = ip.split(":", 1)
                if host.strip().replace(".", "").isdigit():
                    ip = host.strip()
            return ip
        return None

    def _get_item_details(self, item_id: str) -> Dict[str, Any]:
        """
        Fallback: /Sessions ne fournit pas toujours Name/Type dans NowPlayingItem
        (souvent avec Jellyfin Web). On récupère donc l'item complet.
        """
        try:
            # /Items/{id} retourne un objet avec Name + Type généralement fiables
            return self._get_json(f"/Items/{item_id}") or {}
        except Exception:
            return {}




    def get_active_sessions(self) -> List[Dict[str, Any]]:
        # EnableRemoteIP increases chances of having RemoteEndPoint filled
        data = self._get_json("/Sessions?EnableRemoteIP=true")
        sessions: List[Dict[str, Any]] = []

        for s in data or []:
            session_id = s.get("Id")
            user_id = s.get("UserId") or (s.get("User") or {}).get("Id")

            # IMPORTANT:
            # Jellyfin peut garder une "session" même après arrêt,
            # mais avec NowPlayingItem absent (ou vide).
            # Si on la garde, le collecteur ne verra jamais la session "disparaitre"
            # => aucun event "stop" => aucune entrée en history.
            now_playing = s.get("NowPlayingItem") or {}
            item_id = now_playing.get("Id")
            if not session_id or not item_id:
                continue

            play_key = f"{session_id}:{item_id}"
            play_state = s.get("PlayState") or {}
            jf_play_method = (play_state.get("PlayMethod") or "").strip()  # DirectPlay/DirectStream/Transcode

            pm = jf_play_method.lower()
            if pm == "transcode":
                play_method = "transcode"
                is_transcode = 1
            elif pm == "directstream":
                play_method = "directstream"
                is_transcode = 0
            elif pm == "directplay":
                play_method = "directplay"
                is_transcode = 0
            else:
                play_method = "unknown"
                is_transcode = 0

            transcoding_info = s.get("TranscodingInfo") or {}

            # Bitrate Jellyfin : souvent str/float → on normalise
            bitrate = self._to_int(transcoding_info.get("Bitrate"))

            # fallback : certaines versions mettent Bitrate ailleurs
            if bitrate is None:
                bitrate = self._to_int((s.get("NowPlayingItem") or {}).get("Bitrate"))


            is_paused = play_state.get("IsPaused")
            state = "paused" if is_paused else "playing"

            progress_ms = self._ticks_to_ms(play_state.get("PositionTicks"))
            duration_ms = self._ticks_to_ms(now_playing.get("RunTimeTicks"))

            # title/type peuvent être absents ou "Video" selon le client Jellyfin.
            title = (
                now_playing.get("Name")
                or now_playing.get("OriginalTitle")
                or now_playing.get("SortName")
            )
            jf_type = (now_playing.get("Type") or "").strip().lower()

            # ✅ Fallback: si /Sessions est incomplet, récupérer l'item complet
            if not title or jf_type in ("", "unknown", "other"):
                item = self._get_item_details(str(item_id))
                if item:
                    title = title or item.get("Name") or item.get("OriginalTitle")
                    jf_type = jf_type or (item.get("Type") or "").strip().lower()

            # --- Normalize media type (Jellyfin renvoie souvent "Video" pour les films)
            if jf_type in ("movie", "video"):
                media_category = "movie"
            elif jf_type in ("episode",):
                media_category = "serie"
            elif jf_type in ("audio", "musictrack", "song"):
                media_category = "music"
            else:
                media_category = "other"


            # Episode fields when available
            grandparent_title = (
                now_playing.get("SeriesName")
                or now_playing.get("GrandparentTitle")
                or None
            )
            parent_title = (
                now_playing.get("SeasonName")
                or now_playing.get("ParentTitle")
                or None
            )

            client_name = s.get("Client") or s.get("DeviceName")
            client_product = s.get("ApplicationName") or s.get("AppName") or None
            app_version = s.get("ApplicationVersion") or None
            if client_product and app_version:
                client_product = f"{client_product} {app_version}".strip()
            elif not client_product:
                client_product = app_version

            device = s.get("DeviceName") or s.get("DeviceId") or None
            ip = self._pick_ip(s)

            sessions.append(
                {
                    "provider": "jellyfin",
                    "session_key": str(play_key),
                    "external_user_id": str(user_id) if user_id else None,
                    "username": s.get("UserName") or (s.get("User") or {}).get("Name"),
                    "media_key": str(item_id),

                    "media_type": media_category,

                    "title": title,
                    "grandparent_title": grandparent_title,
                    "parent_title": parent_title,
                    "state": state,

                    "progress_ms": progress_ms,
                    "duration_ms": duration_ms,

                    "play_method": play_method,
                    "is_transcode": is_transcode,

                    "video_decision": None,
                    "audio_decision": None,

                    "bitrate": bitrate,
                    "video_codec": (transcoding_info.get("VideoCodec") or None),
                    "audio_codec": (transcoding_info.get("AudioCodec") or None),

                    "client_name": client_name,
                    "client_product": client_product,
                    "device": device,
                    "ip": ip,
                    "raw_json": json.dumps(s, ensure_ascii=False),
                }
            )

        return sessions

