"""Recommended values shown in the comparison table.

Each recommendation comes from the official Plex or Jellyfin documentation and
links to it. They are only shown: VODUM never applies them on its own.
A setting is matched by its key or, for Plex, by the label Plex gives it, so a
renamed key still finds its recommendation.
"""

PLEX_TRANSCODER = "https://support.plex.tv/articles/transcoder/"
PLEX_NETWORK = "https://support.plex.tv/articles/200430283-network/"
PLEX_LIBRARY = "https://support.plex.tv/articles/200289526-library/"
PLEX_TASKS = "https://support.plex.tv/articles/201553286-scheduled-tasks/"
JELLYFIN_TRANSCODING = "https://jellyfin.org/docs/general/post-install/transcoding/"

RECOMMENDATIONS = {
    "plex": (
        {"keys": ("TranscoderQuality",), "labels": ("transcoder quality",), "value": "0",
         "reason": "config_rec_plex_transcoder_quality", "source": PLEX_TRANSCODER},
        {"keys": ("TranscoderH264BackgroundPreset",), "labels": ("background transcoding x264 preset",),
         "value": "veryfast", "reason": "config_rec_plex_background_preset", "source": PLEX_TRANSCODER},
        {"keys": ("TranscodeCountLimit",), "labels": ("maximum simultaneous video transcode",), "value": "0",
         "reason": "config_rec_plex_transcode_limit", "source": PLEX_TRANSCODER},
        {"keys": ("TranscoderToneMapping",), "labels": ("enable hdr tone mapping",), "value": "true",
         "reason": "config_rec_plex_tone_mapping", "source": PLEX_TRANSCODER},
        {"keys": ("HardwareAcceleratedCodecs",), "labels": ("use hardware acceleration when available",),
         "value": "true", "reason": "config_rec_plex_hw_decoding", "source": PLEX_TRANSCODER},
        {"keys": ("HardwareAcceleratedEncoders",), "labels": ("use hardware-accelerated video encoding",),
         "value": "true", "reason": "config_rec_plex_hw_encoding", "source": PLEX_TRANSCODER},
        {"keys": ("secureConnections",), "labels": ("secure connections",), "value": "1",
         "reason": "config_rec_plex_secure_connections", "source": PLEX_NETWORK},
        {"keys": ("DisableTLSv1_0",), "labels": ("strict tls configuration",), "value": "false",
         "reason": "config_rec_plex_strict_tls", "source": PLEX_NETWORK},
        {"keys": ("RelayEnabled",), "labels": ("enable relay",), "value": "true",
         "reason": "config_rec_plex_relay", "source": PLEX_NETWORK},
        {"keys": ("GenerateChapterThumbBehavior",), "labels": ("generate chapter thumbnails",), "value": "scheduled",
         "reason": "config_rec_plex_chapter_thumbnails", "source": PLEX_LIBRARY},
        {"keys": ("OnDeckWindow",), "labels": ("weeks to consider for continue watching",), "value": "16",
         "reason": "config_rec_plex_on_deck_window", "source": PLEX_LIBRARY},
        {"keys": ("DatabaseCacheSize",), "labels": ("database cache size (mb)",), "value": "40",
         "reason": "config_rec_plex_database_cache", "source": PLEX_LIBRARY},
        {"keys": ("ButlerTaskBackupDatabase",), "labels": ("backup database every three days",), "value": "true",
         "reason": "config_rec_plex_backup_database", "source": PLEX_TASKS},
        {"keys": ("ButlerTaskOptimizeDatabase",), "labels": ("optimize database every week",), "value": "true",
         "reason": "config_rec_plex_optimize_database", "source": PLEX_TASKS},
    ),
    "jellyfin": (
        {"keys": ("encoding.EncodingThreadCount",), "labels": (), "value": "-1",
         "reason": "config_rec_jellyfin_thread_count", "source": JELLYFIN_TRANSCODING},
        {"keys": ("encoding.EnableHardwareEncoding",), "labels": (), "value": "true",
         "reason": "config_rec_jellyfin_hw_encoding", "source": JELLYFIN_TRANSCODING},
        {"keys": ("encoding.EnableTonemapping",), "labels": (), "value": "true",
         "reason": "config_rec_jellyfin_tone_mapping", "source": JELLYFIN_TRANSCODING},
    ),
}

_BOOL_ALIASES = {"1": "true", "0": "false"}


def recommendation_for(provider, key, label=None):
    """The recommendation for one setting of a server, or None."""
    key = str(key or "")
    label = " ".join(str(label or "").lower().split())
    for entry in RECOMMENDATIONS.get(str(provider or "").lower(), ()):
        if key in entry["keys"] or (label and label in entry["labels"]):
            return entry
    return None


def follows(entry, value) -> bool:
    """Whether a normalized value matches the recommendation (Plex may send booleans as 1/0)."""
    value = "" if value is None else str(value)
    if entry["value"] in ("true", "false"):
        value = _BOOL_ALIASES.get(value, value.lower())
    return value == entry["value"]
