from __future__ import annotations
import json
import requests
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from core.providers.base import BaseProvider


class PlexProvider(BaseProvider):
    provider_name = "plex"

    def _candidate_bases(self) -> List[str]:
        """
        IMPORTANT: url > local_url > public_url
        car local_url est souvent un 'localhost' / URL docker / mauvais port.
        """
        bases: List[str] = []
        for u in (getattr(self.server, "url", None),
                  getattr(self.server, "local_url", None),
                  getattr(self.server, "public_url", None)):
            if u and str(u).strip():
                b = str(u).strip().rstrip("/")
                if b not in bases:
                    bases.append(b)
        return bases

    def _get(self, path: str) -> str:
        bases = self._candidate_bases()
        if not bases:
            raise RuntimeError("Plex server URL missing")

        token = getattr(self.server, "token", None)
        if not token:
            raise RuntimeError("Plex token missing")

        last_exc: Optional[Exception] = None
        errors: List[str] = []

        for base in bases:
            url = f"{base}{path}"
            try:
                r = requests.get(url, params={"X-Plex-Token": token}, timeout=self.timeout)
                # on veut une VRAIE réponse du serveur
                r.raise_for_status()
                return r.text
            except requests.exceptions.RequestException as e:
                last_exc = e
                code = getattr(getattr(e, "response", None), "status_code", None)
                errors.append(f"{url} -> {code or type(e).__name__}")
                # On tente l'URL suivante si ça ressemble à un problème d'URL/réseau/proxy
                continue

        # Aucune URL n'a fonctionné : on remonte une erreur explicite (utile en logs)
        raise RuntimeError(f"Plex unreachable via any URL. Attempts: {', '.join(errors)}") from last_exc

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        xml_text = self._get("/status/sessions")
        root = ET.fromstring(xml_text)

        sessions: List[Dict[str, Any]] = []
        for node in root:
            media_type = node.tag.lower()
            session_key = node.attrib.get("sessionKey") or node.attrib.get("sessionId") or node.attrib.get("key")
            rating_key = node.attrib.get("ratingKey")

            user = node.find("User")
            external_user_id: Optional[str] = None
            username: Optional[str] = None
            if user is not None:
                external_user_id = user.attrib.get("id")
                username = user.attrib.get("title")

            player = node.find("Player")
            client_product = player.attrib.get("product") if player is not None else None
            client_name = player.attrib.get("title") if player is not None else None
            device = player.attrib.get("device") if player is not None else None
            ip = player.attrib.get("address") if player is not None else None
            state = player.attrib.get("state") if player is not None else None

            progress_ms = node.attrib.get("viewOffset")
            duration_ms = node.attrib.get("duration")

            transcode = node.find("TranscodeSession")
            is_transcode = 1 if transcode is not None else 0
            bitrate = transcode.attrib.get("bandwidth") if transcode is not None else None
            video_codec = transcode.attrib.get("videoCodec") if transcode is not None else None
            audio_codec = transcode.attrib.get("audioCodec") if transcode is not None else None

            title = node.attrib.get("title")
            grandparent = node.attrib.get("grandparentTitle")
            parent = node.attrib.get("parentTitle")

            if not session_key:
                continue

            sessions.append({
                "provider": "plex",
                "session_key": str(session_key),
                "external_user_id": external_user_id,
                "username": username,
                "media_key": rating_key,
                "media_type": "video" if media_type == "video" else "track",
                "title": title,
                "grandparent_title": grandparent,
                "parent_title": parent,
                "state": state or "unknown",
                "progress_ms": int(progress_ms) if progress_ms and str(progress_ms).isdigit() else None,
                "duration_ms": int(duration_ms) if duration_ms and str(duration_ms).isdigit() else None,
                "is_transcode": is_transcode,
                "bitrate": int(bitrate) if bitrate and str(bitrate).isdigit() else None,
                "video_codec": video_codec,
                "audio_codec": audio_codec,
                "client_name": client_name,
                "client_product": client_product,
                "device": device,
                "ip": ip,
                "raw_json": json.dumps({
                    "VideoOrTrack": dict(node.attrib),
                    "User": dict(user.attrib) if user is not None else None,
                    "Player": dict(player.attrib) if player is not None else None,
                    "TranscodeSession": dict(transcode.attrib) if transcode is not None else None,
                    "Media": [dict(m.attrib) for m in node.findall("Media")] if node is not None else [],
                }, ensure_ascii=False),
            })

        return sessions
