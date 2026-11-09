from core.error_reporting import log_handled_failure
import json
import re
from html.parser import HTMLParser

from mailing_utils import build_user_context, render_mail


def readable_history_body(body):
    body=str(body or '')
    if not re.search(r'<(?:br|p|div|a|html|table)\b',body,re.I):return body
    class TextReader(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts=[]
            self.hidden=0
        def handle_starttag(self,tag,attrs):
            if tag in ('script','style'):self.hidden+=1
            if not self.hidden and tag in ('br','p','div','tr'):self.parts.append('\n')
        def handle_endtag(self,tag):
            if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
            if not self.hidden and tag in ('p','div','tr'):self.parts.append('\n')
        def handle_data(self,data):
            if not self.hidden:self.parts.append(data)
    reader=TextReader();reader.feed(body)
    return re.sub(r'\n{3,}','\n\n',''.join(reader.parts)).strip()


def render_communication_history_message(row: dict, brand_name: str, portal_public_url: str | None = None) -> dict:
    try:
        metadata = json.loads(row.get("meta_json") or "{}")
    except Exception:
        log_handled_failure("communications.decode_history_metadata")
        metadata = {}
    if metadata.get("rendered_subject") or metadata.get("rendered_body"):
        row["template_name"] = metadata.get("template_name") or row.get("template_name") or ""
        row["rendered_subject"] = metadata.get("rendered_subject") or ""
        row["rendered_body"] = readable_history_body(metadata.get("rendered_body"))
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
        "portal_public_url": portal_public_url,
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
    row["rendered_body"] = readable_history_body(render_mail(body or "", context))
    return row
