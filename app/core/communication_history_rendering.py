import json

from mailing_utils import build_user_context, render_mail


def render_communication_history_message(row: dict, brand_name: str) -> dict:
    try:
        metadata = json.loads(row.get("meta_json") or "{}")
    except Exception:
        metadata = {}
    if metadata.get("rendered_subject") or metadata.get("rendered_body"):
        row["rendered_subject"] = metadata.get("rendered_subject") or ""
        row["rendered_body"] = metadata.get("rendered_body") or ""
        return row
    payload = metadata.get("payload") or {}
    context_input = {
        "id": row.get("user_id"), "username": row.get("user_username") or "",
        "firstname": row.get("user_firstname") or "", "lastname": row.get("user_lastname") or "",
        "email": row.get("user_email") or "", "expiration_date": row.get("user_expiration_date") or "",
        "subscription_template_id": row.get("user_subscription_template_id"),
        "subscription_name": row.get("subscription_name") or "",
        "subscription_duration_days": row.get("subscription_duration_days") or "",
        "subscription_value": row.get("subscription_value") or "", "brand_name": brand_name,
    }
    context_input.update(metadata)
    context_input.update(payload)
    context_input["brand_name"] = metadata.get("brand_name") or payload.get("brand_name") or brand_name
    context = build_user_context(context_input)
    for key, value in context_input.items():
        if value not in (None, ""):
            context[key] = str(value)
    subject = row.get("template_subject") if row.get("kind") == "template" else row.get("campaign_subject")
    body = row.get("template_body") if row.get("kind") == "template" else row.get("campaign_body")
    row["rendered_subject"] = render_mail(subject or "", context)
    row["rendered_body"] = render_mail(body or "", context)
    return row
