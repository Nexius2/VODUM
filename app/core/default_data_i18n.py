"""Localize bundled default data that nobody has changed yet.

Admin-facing names (communication templates, subscription plans) follow the
admin interface language. Messages sent to users get one bundled translation
per language, so each user receives the default text in their own language.
A value is only replaced while it still equals one of the bundled versions.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.error_reporting import log_handled_failure

LANGUAGES = ("en", "fr", "de", "es", "it")
_ROOTS = (Path("/app/translations"), Path(__file__).resolve().parents[2] / "translations")
_CACHE: dict[tuple[str, str], dict] = {}

SUBSCRIPTION_KEYS = ("base", "family", "plus", "lifetime")


def _catalog(kind: str, language: str) -> dict:
    cache_key = (kind, language)
    if cache_key not in _CACHE:
        data = {}
        for root in _ROOTS:
            path = root / kind / f"{language}.json"
            try:
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8")) or {}
                    break
            except Exception:
                log_handled_failure("default_data_i18n.load_catalog")
        _CACHE[cache_key] = data if isinstance(data, dict) else {}
    return _CACHE[cache_key]


def normalize_language(language) -> str:
    language = str(language or "").strip().lower()
    return language if language in LANGUAGES else "en"


def bundled_comm_template(key: str, language: str) -> dict | None:
    entry = (_catalog("communication", normalize_language(language)).get("default_templates") or {}).get(key)
    return entry if isinstance(entry, dict) and entry.get("subject") and entry.get("body") else None


def _copy_suffix(language: str) -> str:
    return str((_catalog("communication", normalize_language(language)).get("default_templates") or {}).get("copy_suffix") or "Default")


def _english_variants() -> dict[str, set[tuple[str, str]]]:
    from core.communications.default_templates import DEFAULT_COMM_TEMPLATES
    from core.db_bootstrap_communications import STREAM_BLOCKED_SEED_BODY, STREAM_BLOCKED_SEED_SUBJECT
    from core.db_bootstrap_usage_risk_template import USAGE_RISK_BODY, USAGE_RISK_SUBJECT

    from core.db_bootstrap_comm_defaults import SEED_COMM_TEMPLATES

    variants: dict[str, set[tuple[str, str]]] = {}
    for template in (*DEFAULT_COMM_TEMPLATES, *SEED_COMM_TEMPLATES):
        variants.setdefault(template["key"], set()).add((template["subject"], template["body"]))
    variants.setdefault("stream_blocked", set()).add((STREAM_BLOCKED_SEED_SUBJECT, STREAM_BLOCKED_SEED_BODY))
    variants.setdefault("usage_risk_upgrade_suggestion", set()).add((USAGE_RISK_SUBJECT, USAGE_RISK_BODY))
    for key in variants:
        english = bundled_comm_template(key, "en")
        if english:
            variants[key].add((english["subject"], english["body"]))
    return variants


class _CursorDb:
    """Small adapter so bootstrap code (sqlite cursor) and DBManager share one path."""

    def __init__(self, cursor):
        self.cursor = cursor

    def query(self, sql, params=()):
        self.cursor.execute(sql, params)
        names = [column[0] for column in self.cursor.description or ()]
        return [dict(zip(names, row)) for row in self.cursor.fetchall()]

    def execute(self, sql, params=()):
        self.cursor.execute(sql, params)


def _rows(db, sql, params=()):
    return [dict(row) for row in (db.query(sql, params) or [])]


def localize_comm_templates(db, admin_language: str | None) -> int:
    """Return the number of rows changed."""
    admin_language = normalize_language(admin_language)
    variants = _english_variants()
    keys = list(variants)
    placeholders = ",".join("?" for _ in keys)
    restore_keys = [key + "_restore_default" for key in keys]
    templates = _rows(
        db,
        f"SELECT id, key, name, subject, body FROM comm_templates WHERE key IN ({placeholders}) OR key IN ({placeholders})",
        (*keys, *restore_keys),
    )
    changed = 0
    for template in templates:
        restore = template["key"].endswith("_restore_default")
        key = template["key"][: -len("_restore_default")] if restore else template["key"]
        bundled = {language: bundled_comm_template(key, language) for language in LANGUAGES}
        if not all(bundled.values()):
            continue
        english = variants.get(key, set())
        known = english | {(entry["subject"], entry["body"]) for entry in bundled.values()}

        names = {entry["name"] for entry in bundled.values()}
        current_name = str(template.get("name") or "")
        wanted_name = bundled[admin_language]["name"]
        if restore:
            names = {f"{name} - {_copy_suffix(language)}" for name in names for language in LANGUAGES}
            wanted_name = f"{wanted_name} - {_copy_suffix(admin_language)}"
        if current_name in names and current_name != wanted_name:
            db.execute("UPDATE comm_templates SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (wanted_name, template["id"]))
            changed += 1

        translations = _rows(
            db,
            "SELECT id, language, subject, body FROM comm_template_translations WHERE template_id=?",
            (template["id"],),
        )
        present = {row["language"] for row in translations}
        for row in translations:
            language = row["language"]
            if language in LANGUAGES and language != "en" and (row["subject"], row["body"]) in english:
                entry = bundled[language]
                db.execute(
                    "UPDATE comm_template_translations SET subject=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (entry["subject"], entry["body"], row["id"]),
                )
                changed += 1

        pristine = (template["subject"], template["body"]) in english and all(
            (row["subject"], row["body"]) in known for row in translations
        )
        if not pristine:
            continue
        for language in LANGUAGES:
            if language in present:
                continue
            subject, body = (template["subject"], template["body"]) if language == "en" else (
                bundled[language]["subject"], bundled[language]["body"])
            db.execute(
                """INSERT OR IGNORE INTO comm_template_translations(template_id, language, subject, body, created_at, updated_at)
                   VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (template["id"], language, subject, body),
            )
            changed += 1
    return changed


def bundled_subscription_texts(index: int, language: str) -> tuple[str, str] | None:
    from core.default_subscription_templates import DEFAULT_SUBSCRIPTION_TEMPLATES

    language = normalize_language(language)
    if language == "en":
        default = DEFAULT_SUBSCRIPTION_TEMPLATES[index]
        return default[0], default[1]
    catalog = _catalog("ui", language)
    key = SUBSCRIPTION_KEYS[index]
    name = catalog.get(f"default_subscription.{key}.name")
    notes = catalog.get(f"default_subscription.{key}.notes")
    return (name, notes) if name and notes else None


def subscription_name_variants(index: int) -> set[str]:
    return {texts[0] for language in LANGUAGES if (texts := bundled_subscription_texts(index, language))}


def localize_subscription_templates(db, admin_language: str | None) -> int:
    from core.default_subscription_templates import DEFAULT_SUBSCRIPTION_TEMPLATES

    admin_language = normalize_language(admin_language)
    changed = 0
    for index in range(len(DEFAULT_SUBSCRIPTION_TEMPLATES)):
        wanted = bundled_subscription_texts(index, admin_language)
        if not wanted:
            continue
        versions = [texts for language in LANGUAGES if (texts := bundled_subscription_texts(index, language))]
        names = {name for name, _ in versions}
        notes = {note for _, note in versions}
        placeholders = ",".join("?" for _ in names)
        for row in _rows(db, f"SELECT id, name, notes FROM subscription_templates WHERE name IN ({placeholders})", tuple(names)):
            new_notes = wanted[1] if (row.get("notes") or "") in notes else row.get("notes")
            if row["name"] != wanted[0] or new_notes != row.get("notes"):
                if _rows(db, "SELECT id FROM subscription_templates WHERE name=? AND id<>?", (wanted[0], row["id"])):
                    continue
                db.execute("UPDATE subscription_templates SET name=?, notes=? WHERE id=?", (wanted[0], new_notes, row["id"]))
                changed += 1
    return changed


def localize_default_data(db, admin_language: str | None) -> int:
    changed = 0
    for step in (localize_comm_templates, localize_subscription_templates):
        try:
            changed += step(db, admin_language)
        except Exception:
            log_handled_failure("default_data_i18n." + step.__name__)
    return changed


def localize_default_data_on_bootstrap(conn, cursor) -> None:
    db = _CursorDb(cursor)
    try:
        row = db.query("SELECT default_language FROM settings WHERE id = 1")
        language = row[0]["default_language"] if row else None
    except Exception:
        log_handled_failure("default_data_i18n.read_language")
        language = None
    changed = localize_default_data(db, language)
    conn.commit()
    if changed:
        print(f"✔ Default data localized: {changed} change(s)")


# ---------------------------------------------------------------------------
# Messages shown on the player when a stream is stopped
# ---------------------------------------------------------------------------

_LIMIT_TITLES = {"Stream limit", "Streaming limit reached"}
_LIMIT_TEXTS = {
    "Limit reached.",
    "You have reached the allowed number of simultaneous streams",
    "You have reached your streaming limit. The most recent stream will be stopped if it continues.",
    "You reached your limit. If this continues, the most recent stream will be stopped.",
}
_EXPIRED_TITLES = {"Subscription expired"}
_EXPIRED_TEXTS = {"Your subscription has ended. Please renew to restore access."}


def _policy_catalog(language: str) -> dict:
    return _catalog("communication", normalize_language(language)).get("policy") or {}


def _known(values: set[str], catalog_key: str, *, kind: str = "communication") -> set[str]:
    known = {value.strip().rstrip(".") for value in values}
    for language in LANGUAGES:
        source = _policy_catalog(language) if kind == "communication" else _catalog("ui", language)
        value = source.get(catalog_key)
        if value:
            known.add(str(value).strip().rstrip("."))
    return known


def localize_default_warning(title: str | None, text: str | None, language: str | None) -> tuple[str | None, str | None]:
    """Translate a stop message only while it is still a bundled default."""
    language = normalize_language(language)
    policy = _policy_catalog(language)
    ui = _catalog("ui", language)

    def same(value, known):
        return value is not None and str(value).strip().rstrip(".") in known

    if same(title, _known(_LIMIT_TITLES, "policies_warn_title_default", kind="ui")):
        title = ui.get("policies_warn_title_default") or title
    elif same(title, _known(_EXPIRED_TITLES, "warn_title_expired")):
        title = policy.get("warn_title_expired") or title
    if same(text, _known(_LIMIT_TEXTS, "policies_warn_text_default", kind="ui")):
        text = ui.get("policies_warn_text_default") or text
    elif same(text, _known(_EXPIRED_TEXTS, "subscription_expired")):
        text = policy.get("subscription_expired") or text
    return title, text
