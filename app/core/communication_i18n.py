from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict


SUPPORTED_COMMUNICATION_LANGUAGES = ("en", "fr", "es", "de", "it")
DEFAULT_COMMUNICATION_LANGUAGE = "en"


def normalize_communication_language(value: str | None) -> str:
    lang = (value or "").strip().lower()
    return lang if lang in SUPPORTED_COMMUNICATION_LANGUAGES else DEFAULT_COMMUNICATION_LANGUAGE


def communication_language_options() -> list[dict[str, str]]:
    names = {
        "en": "English",
        "fr": "Français",
        "es": "Español",
        "de": "Deutsch",
        "it": "Italiano",
    }
    return [{"code": code, "name": names[code]} for code in SUPPORTED_COMMUNICATION_LANGUAGES]


def resolve_communication_language(settings: dict | None = None, user: dict | None = None) -> str:
    user_lang = (user or {}).get("preferred_language")
    if user_lang:
        return normalize_communication_language(str(user_lang))

    settings_lang = (settings or {}).get("communication_language")
    if settings_lang:
        return normalize_communication_language(str(settings_lang))

    return DEFAULT_COMMUNICATION_LANGUAGE


def _candidate_translation_paths(lang: str) -> list[str]:
    here = os.path.dirname(__file__)
    app_dir = os.path.abspath(os.path.join(here, ".."))
    repo_dir = os.path.abspath(os.path.join(app_dir, ".."))
    return [
        os.path.join("/app", "translations", "communication", f"{lang}.json"),
        os.path.join(repo_dir, "translations", "communication", f"{lang}.json"),
    ]


@lru_cache(maxsize=16)
def load_communication_catalog(lang: str) -> dict:
    lang = normalize_communication_language(lang)
    for path in _candidate_translation_paths(lang):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            continue
    return {}


def _lookup(data: dict, key: str) -> Any:
    current: Any = data
    for part in (key or "").split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def communication_translate(key: str, lang: str, variables: dict | None = None) -> str:
    key = (key or "").strip()
    if not key:
        return ""

    lang = normalize_communication_language(lang)
    text = _lookup(load_communication_catalog(lang), key)
    if text is None and lang != DEFAULT_COMMUNICATION_LANGUAGE:
        text = _lookup(load_communication_catalog(DEFAULT_COMMUNICATION_LANGUAGE), key)
    if text is None:
        text = key

    try:
        return str(text).format(**(variables or {}))
    except Exception:
        return str(text)


def resolve_generated_payload_text(payload: dict | None, lang: str) -> Dict[str, str]:
    payload = payload or {}
    resolved: Dict[str, str] = {}

    for field in ("policy_reason", "policy_explanation", "policy_limit_label"):
        key = payload.get(f"{field}_key")
        if not key:
            continue

        key = str(key).strip()
        if "." not in key:
            key = f"policy.{key}"

        variables = payload.get(f"{field}_variables") or {}
        if not isinstance(variables, dict):
            variables = {}

        resolved[field] = communication_translate(key, lang, variables)

    return resolved
