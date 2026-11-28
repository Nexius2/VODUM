"""Settings that Plex or Jellyfin only list while another setting allows them.

Plex does not return "Enable HEVC Optimization" at all while "Enable HEVC video
Encoding" is set to "Never": the setting looks absent from that server although
it exists. VODUM explains it, and changing the hidden setting first turns the
setting it depends on back on (both changes are shown in the preview).

Entries are matched by key or by label, like recommendations, since Plex keys
are not documented. Add an entry only for a dependency seen on a real server.
"""

from __future__ import annotations

DEPENDENCIES = (
    {
        "provider": "plex",
        "keys": ("TranscoderHEVCOptimize",),
        "labels": ("enable hevc optimization",),
        "label": "Enable HEVC Optimization",
        "parent_keys": (),
        "parent_labels": ("enable hevc video encoding",),
        "off_labels": ("never",),
        "off_values": (),
    },
)


def _lower(value) -> str:
    return str(value or "").strip().lower()


def dependency_for(provider, key, label=None):
    """The dependency of a setting, or None. Library settings never match."""
    provider = _lower(provider)
    name = str(key or "")
    if name.startswith("library."):
        return None
    for entry in DEPENDENCIES:
        if entry["provider"] != provider:
            continue
        if name in entry["keys"] or (label and _lower(label) in entry["labels"]):
            return entry
    return None


def find_parent(entry, settings):
    """The setting the dependency relies on, among one server's settings ({compare_key: setting})."""
    for key, item in (settings or {}).items():
        if item.get("library"):
            continue
        if key in entry["parent_keys"] or _lower(item.get("label")) in entry["parent_labels"]:
            return item
    return None


def _label_of(item, value) -> str:
    for choice in item.get("choices") or []:
        if str(choice.get("value")) == str(value):
            return str(choice.get("label") or value)
    return str(value)


def is_off(entry, parent) -> bool:
    value = str(parent.get("value") if parent.get("value") is not None else "")
    return value in entry["off_values"] or _lower(_label_of(parent, value)) in entry["off_labels"]


def enabling_value(entry, parent):
    """The value that makes the hidden setting appear: the platform default, else the first other choice."""
    default = parent.get("default")
    if default not in (None, "") and not is_off(entry, {**parent, "value": default}):
        return str(default)
    for choice in parent.get("choices") or []:
        if not is_off(entry, {**parent, "value": choice.get("value")}):
            return str(choice.get("value"))
    return None


def hidden_by(provider, key, label, settings):
    """Why a setting is missing from one server: {parent_key, parent_label, current, enable, enable_display}, or None."""
    entry = dependency_for(provider, key, label)
    if not entry:
        return None
    parent = find_parent(entry, settings)
    if not parent or not is_off(entry, parent):
        return None
    enable = enabling_value(entry, parent)
    if enable is None:
        return None
    return {
        "entry": entry,
        "parent_key": parent.get("compare_key") or parent.get("key"),
        "parent_label": parent.get("label") or parent.get("key"),
        "parent_category": parent.get("category") or "advanced",
        "current": _label_of(parent, parent.get("value")),
        "enable": enable,
        "enable_display": _label_of(parent, enable),
        "editable": bool(parent.get("writable")) and not parent.get("sensitive")
                    and parent.get("source") != "scheduled_task",
    }
