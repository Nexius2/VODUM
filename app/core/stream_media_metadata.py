from typing import Optional

from core.stream_policy_utils import loads_json


def parse_media_height(provider: str, raw_json: str) -> Optional[int]:
    data = loads_json(raw_json)
    if provider == "plex":
        for media in data.get("Media") or []:
            if not isinstance(media, dict):
                continue
            height = media.get("height")
            if isinstance(height, str) and height.isdigit():
                return int(height)
            if isinstance(height, int):
                return height
            if (media.get("videoResolution") or "").lower() in ("4k", "uhd"):
                return 2160
        for part in data.get("Part") or []:
            if not isinstance(part, dict):
                continue
            height = part.get("height")
            if isinstance(height, str) and height.isdigit():
                return int(height)
            if isinstance(height, int):
                return height
    elif provider == "jellyfin":
        item = data.get("NowPlayingItem") or {}
        if isinstance(item, dict):
            height = item.get("Height")
            if isinstance(height, int):
                return height
            if isinstance(height, str) and height.isdigit():
                return int(height)
            for stream in item.get("MediaStreams") or []:
                if isinstance(stream, dict) and stream.get("Type") == "Video":
                    height = stream.get("Height")
                    if isinstance(height, int):
                        return height
                    if isinstance(height, str) and height.isdigit():
                        return int(height)
    return None
