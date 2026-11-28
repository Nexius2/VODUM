"""Readable video quality for live sessions, read from the stored provider payload."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_CODECS = {
    "h264": "H.264", "avc": "H.264", "avc1": "H.264",
    "hevc": "HEVC", "h265": "HEVC", "hvc1": "HEVC", "hev1": "HEVC",
    "av1": "AV1", "vp9": "VP9", "vp8": "VP8",
    "mpeg2video": "MPEG-2", "mpeg2": "MPEG-2", "mpeg4": "MPEG-4",
    "vc1": "VC-1", "wmv3": "WMV",
}
_RESOLUTION_TOKEN = re.compile(r"\b(8k|4k|\d{3,4}p|sd)\b", re.IGNORECASE)


def _int(value) -> Optional[int]:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _codec(value) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return _CODECS.get(text.lower(), text.upper())


def _resolution_from_size(width=None, height=None) -> Optional[str]:
    width, height = _int(width), _int(height)
    if not width and not height:
        return None
    width = width or 0
    height = height or 0
    # Width first: cropped widescreen films (1920x800) are still 1080p.
    if width >= 6000 or height >= 3400:
        return "8K"
    if width >= 3200 or height >= 1800:
        return "4K"
    if width >= 1700 or height >= 950:
        return "1080p"
    if width >= 1100 or height >= 650:
        return "720p"
    if height >= 540:
        return "576p"
    if height >= 400:
        return "480p"
    return "SD"


def _resolution_label(value) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"4k", "uhd", "2160", "2160p"}:
        return "4K"
    if text in {"8k", "4320", "4320p"}:
        return "8K"
    if text == "sd":
        return "SD"
    if text.endswith("p"):
        text = text[:-1]
    return f"{text}p" if text.isdigit() else None


def _label(resolution, codec, dynamic_range=None) -> Optional[str]:
    parts = [part for part in (resolution, codec, dynamic_range) if part]
    return " ".join(parts) or None


def _plex_dynamic_range(stream: dict) -> Optional[str]:
    if str(stream.get("DOVIPresent") or "") == "1":
        return "Dolby Vision"
    title = f"{stream.get('extendedDisplayTitle') or ''} {stream.get('displayTitle') or ''}".lower()
    if "dolby vision" in title or "dovi" in title:
        return "Dolby Vision"
    if "hdr" in title or str(stream.get("colorTrc") or "").lower() in {"smpte2084", "arib-std-b67"}:
        return "HDR"
    return None


def _plex_quality(raw: dict) -> Optional[dict]:
    medias = [m for m in (raw.get("Media") or []) if isinstance(m, dict)]
    media = next((m for m in medias if str(m.get("selected") or "") == "1"), medias[0] if medias else {})
    stream = raw.get("VideoStream") if isinstance(raw.get("VideoStream"), dict) else {}
    transcode = raw.get("TranscodeSession") if isinstance(raw.get("TranscodeSession"), dict) else {}
    computed = raw.get("Computed") if isinstance(raw.get("Computed"), dict) else {}
    if not media.get("videoCodec") and not media.get("videoResolution") and not stream:
        return None  # music or no video information

    decision = str(
        computed.get("videoDecision") or transcode.get("videoDecision")
        or stream.get("decision") or ""
    ).strip().lower().replace(" ", "")
    media_resolution = (_resolution_label(media.get("videoResolution"))
                        or _resolution_from_size(media.get("width"), media.get("height")))
    dynamic_range = _plex_dynamic_range(stream)

    if decision != "transcode":
        return {
            "source": _label(media_resolution, _codec(media.get("videoCodec")), dynamic_range),
            "stream": None,
            "video_transcoded": False,
        }

    # During a video transcode Plex describes the output in Media/Part.
    title_match = _RESOLUTION_TOKEN.search(
        str(stream.get("displayTitle") or stream.get("extendedDisplayTitle") or "")
    )
    source_resolution = _resolution_label(title_match.group(1)) if title_match else None
    source = _label(
        source_resolution,
        _codec(transcode.get("sourceVideoCodec")),
        dynamic_range,
    ) if source_resolution else None
    output = _label(
        _resolution_from_size(transcode.get("width"), transcode.get("height")) or media_resolution,
        _codec(transcode.get("videoCodec") or media.get("videoCodec")),
    )
    return {"source": source, "stream": output, "video_transcoded": True}


def _jellyfin_dynamic_range(stream: dict) -> Optional[str]:
    range_type = str(stream.get("VideoRangeType") or "").upper()
    if range_type.startswith("DOVI"):
        return "Dolby Vision"
    if str(stream.get("VideoRange") or "").upper() == "HDR" or range_type.startswith(("HDR", "HLG")):
        return "HDR"
    return None


def _jellyfin_quality(raw: dict) -> Optional[dict]:
    item = raw.get("NowPlayingItem") if isinstance(raw.get("NowPlayingItem"), dict) else {}
    video = next(
        (s for s in (item.get("MediaStreams") or [])
         if isinstance(s, dict) and str(s.get("Type") or "").lower() == "video"),
        {},
    )
    resolution = (_resolution_from_size(video.get("Width"), video.get("Height"))
                  or _resolution_from_size(item.get("Width"), item.get("Height")))
    source = _label(resolution, _codec(video.get("Codec")), _jellyfin_dynamic_range(video))
    play_state = raw.get("PlayState") if isinstance(raw.get("PlayState"), dict) else {}
    info = raw.get("TranscodingInfo") if isinstance(raw.get("TranscodingInfo"), dict) else {}
    video_transcoded = (
        str(play_state.get("PlayMethod") or "").lower() == "transcode"
        and bool(info) and info.get("IsVideoDirect") is False
    )
    if not source and not video_transcoded:
        return None
    if not video_transcoded:
        return {"source": source, "stream": None, "video_transcoded": False}
    output = _label(
        _resolution_from_size(info.get("Width"), info.get("Height")),
        _codec(info.get("VideoCodec")),
    )
    return {"source": source, "stream": output, "video_transcoded": True}


def describe_video_quality(provider: Any, raw_json: Any) -> Optional[dict]:
    """Return {"source", "stream", "video_transcoded"}, or None without video data."""
    try:
        raw = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    provider = str(provider or "").strip().lower()
    try:
        if provider == "plex":
            quality = _plex_quality(raw)
        elif provider == "jellyfin":
            quality = _jellyfin_quality(raw)
        else:
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    if not quality or not (quality.get("source") or quality.get("stream")):
        return None
    return quality
