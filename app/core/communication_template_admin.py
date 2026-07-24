from core.communication_i18n import normalize_communication_language
from notifications_utils import parse_notifications_order
from secret_store import encrypt_secret


def sanitize_template_key(raw: str) -> str:
    raw = (raw or "").strip().lower().replace(" ", "_")
    return "".join(character for character in raw if character.isalnum() or character in ("_", "-"))


def sanitize_notifications_order(raw: str) -> str:
    parts = parse_notifications_order(raw)
    return ",".join(parts) if parts else "email"


def encrypted_secret_from_form(raw_value, existing_value, *, empty_existing=None):
    if raw_value is None or not str(raw_value).strip():
        return existing_value if existing_value is not None else empty_existing
    return encrypt_secret(str(raw_value).strip())


def upsert_template_translation(db, template_id: int, language: str, subject: str, body: str) -> None:
    language = normalize_communication_language(language)
    db.execute("""
        INSERT INTO comm_template_translations(template_id, language, subject, body, created_at, updated_at)
        VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(template_id, language) DO UPDATE SET
            subject=excluded.subject, body=excluded.body, updated_at=CURRENT_TIMESTAMP
    """, (int(template_id), language, subject or "", body or ""))


def apply_template_translation(db, template: dict | None, language: str) -> dict | None:
    if not template:
        return template
    row = db.query_one("""
        SELECT subject, body FROM comm_template_translations
        WHERE template_id = ? AND language = ? LIMIT 1
    """, (int(template["id"]), normalize_communication_language(language)))
    if row:
        translated = dict(row)
        template["subject"] = translated.get("subject") or ""
        template["body"] = translated.get("body") or ""
    return template
