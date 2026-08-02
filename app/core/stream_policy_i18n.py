import json
from pathlib import Path


_CACHE: dict[str, dict] = {}


def _language(db) -> str:
    try:
        row = db.query_one("SELECT default_language FROM settings WHERE id = 1")
        language = str((dict(row) if row else {}).get("default_language") or "en").strip().lower()
        return language or "en"
    except Exception:
        return "en"


def _load(language: str) -> dict:
    language = (language or "en").strip().lower()
    if language in _CACHE:
        return _CACHE[language]

    paths = (
        Path("/app/translations/ui") / f"{language}.json",
        Path(__file__).resolve().parents[2] / "translations" / "ui" / f"{language}.json",
    )
    data = {}
    for path in paths:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8")) or {}
                break
        except Exception:
            data = {}
    _CACHE[language] = data
    return data


def translate_policy(db, key: str, **kwargs) -> str:
    data = _load(_language(db))
    fallback = _load("en")
    text = data.get(key) or fallback.get(key) or key
    try:
        return str(text).format(**kwargs)
    except Exception:
        return str(text)
