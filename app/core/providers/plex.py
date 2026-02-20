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

            # Évite les "192.168.1.60:32400" sans schéma
            if not (b.startswith("http://") or b.startswith("https://")):
                continue

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

    def _request(self, method: str, path: str, params: Optional[dict] = None) -> bool:
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
                p = {"X-Plex-Token": token}
                if params:
                    p.update(params)

                r = requests.request(method, url, params=p, timeout=self.timeout)
                r.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                last_exc = e
                code = getattr(getattr(e, "response", None), "status_code", None)
                errors.append(f"{method} {url} -> {code or type(e).__name__}")
                continue

        raise RuntimeError(f"Plex request failed. Attempts: {', '.join(errors)}") from last_exc


    def terminate_session(self, session_key: str, reason: str = "") -> bool:
        """
        Plex: /status/sessions/terminate attend sessionId (= l'id de la balise <Session id="...">),
        qui n'est pas toujours égal au sessionKey.
        Donc:
          - on recharge /status/sessions
          - on retrouve la bonne sessionId
          - on appelle terminate avec la bonne valeur
        """
        # 1) charger /status/sessions (XML brut)
        xml_text = self._get("/status/sessions")
        root = ET.fromstring(xml_text)

        target_session_id = None

        # 2) retrouver la session correspondante au session_key
        for node in root:
            # sessionKey est souvent sur le node (Video/Track/Episode)
            sk = node.attrib.get("sessionKey") or node.attrib.get("sessionId") or node.attrib.get("key")
            if not sk:
                continue
            if str(sk) != str(session_key):
                continue

            # la vraie sessionId est généralement dans <Session id="...">
            sess = node.find("Session")
            if sess is not None:
                sid = sess.attrib.get("id")
                if sid:
                    target_session_id = str(sid)
                    break

            # fallback (au cas où) : certaines versions exposent sessionId directement
            if node.attrib.get("sessionId"):
                target_session_id = str(node.attrib["sessionId"])
                break

        # 3) si on n'a pas trouvé, on tente quand même avec session_key (mais on logge clairement)
        if not target_session_id:
            target_session_id = str(session_key)

        params = {"sessionId": target_session_id}
        if reason:
            params["reason"] = reason[:120]

        # GET puis POST (compat)
        try:
            return self._request("GET", "/status/sessions/terminate", params=params)
        except Exception:
            return self._request("POST", "/status/sessions/terminate", params=params)



    def get_active_sessions(self) -> List[Dict[str, Any]]:
        xml_text = self._get("/status/sessions")
        root = ET.fromstring(xml_text)

        def _first_decision(node: ET.Element, attr: str) -> Optional[str]:
            # 1) Media
            for m in node.findall("Media"):
                v = m.attrib.get(attr)
                if v:
                    return v

            # 2) Part
            for p in node.findall(".//Part"):
                v = p.attrib.get(attr)
                if v:
                    return v

            # 3) TranscodeSession (important !)
            ts = node.find("TranscodeSession")
            if ts is not None:
                v = ts.attrib.get(attr)
                if v:
                    return v

            return None


        def _normalize_decision(v: Optional[str]) -> Optional[str]:
            if not v:
                return None
            v = str(v).strip().lower()

            # normalise "direct play" / "direct_play" / etc -> "directplay"
            v = v.replace(" ", "").replace("_", "").replace("-", "")

            return v or None


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
            library_section_id = node.attrib.get("librarySectionID") or None


            progress_ms = node.attrib.get("viewOffset")
            duration_ms = node.attrib.get("duration")

            # --- NEW: decisions (truth source)
            video_decision = _normalize_decision(_first_decision(node, "videoDecision"))
            audio_decision = _normalize_decision(_first_decision(node, "audioDecision"))

            decisions = {d for d in (video_decision, audio_decision) if d}

            # Play method classification (useful for UI + stats)
            if "transcode" in decisions:
                play_method = "transcode"
                is_transcode = 1
            elif "copy" in decisions:
                play_method = "directstream"
                is_transcode = 0
            elif decisions and decisions.issubset({"directplay"}):
                play_method = "directplay"
                is_transcode = 0
            else:
                # fallback: no decision present => don't lie
                play_method = "unknown"
                is_transcode = 0

            # Keep transcode session for bitrate/codecs, but don't use it as the "truth" for is_transcode
            transcode = node.find("TranscodeSession")

            # --- Bitrate (Plex can put it in different places depending on direct play / direct stream / transcode) ---
            bitrate = None

            # 1) Transcode session bitrate (when transcoding)
            if transcode is not None:
                bitrate = transcode.attrib.get("bandwidth") or transcode.attrib.get("peakBandwidth")

            # 2) Sometimes on the session node itself
            if not bitrate:
                bitrate = node.attrib.get("bandwidth") or node.attrib.get("bitrate")

            # 3) Sometimes on Player
            if not bitrate and player is not None:
                bitrate = player.attrib.get("bandwidth") or player.attrib.get("bitrate")

            # 4) Fallback: Media/Part bitrate
            if not bitrate:
                bitrate = _first_decision(node, "bitrate")

            video_codec = transcode.attrib.get("videoCodec") if transcode is not None else None
            audio_codec = transcode.attrib.get("audioCodec") if transcode is not None else None


            title = node.attrib.get("title")
            grandparent = node.attrib.get("grandparentTitle")
            parent = node.attrib.get("parentTitle")

            if not session_key:
                continue

            plex_type = node.attrib.get("type")  # movie / episode / track

            if plex_type == "movie":
                media_category = "movie"
            elif plex_type == "episode":
                media_category = "serie"
            elif plex_type == "track":
                media_category = "music"
            else:
                media_category = "other"


            sessions.append({
                "provider": "plex",
                "session_key": str(session_key),
                "external_user_id": external_user_id,
                "username": username,
                "media_key": rating_key,
                "media_type": media_category,
                "title": title,
                "grandparent_title": grandparent,
                "parent_title": parent,
                "state": state or "unknown",
                "progress_ms": int(progress_ms) if progress_ms and str(progress_ms).isdigit() else None,
                "duration_ms": int(duration_ms) if duration_ms and str(duration_ms).isdigit() else None,
                "library_section_id": library_section_id,


                # --- NEW: store decisions
                "video_decision": video_decision,
                "audio_decision": audio_decision,
                "play_method": play_method,

                # existing
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
                    "Computed": {
                        "videoDecision": video_decision,
                        "audioDecision": audio_decision,
                        "play_method": play_method,
                        "is_transcode": is_transcode,
                    }
                }, ensure_ascii=False),
            })

        return sessions

