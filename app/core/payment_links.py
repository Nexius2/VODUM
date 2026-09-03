import json
import re
from urllib.parse import quote, urlsplit


METHOD_TYPES = {"paypal_me", "wero", "bank_transfer", "custom"}
REFERENCE_VARIABLES = {"username", "user_id", "plan", "amount", "currency"}


def valid_external_url(value):
    text = str(value or "").strip()
    if any(ord(character) < 32 for character in text):
        return None
    try:
        parsed = urlsplit(text)
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return text


def load_payment_links_admin(db):
    settings = db.query_one("SELECT portal_payment_links_enabled,portal_show_payment,debug_mode,subscription_currency FROM settings WHERE id=1")
    rows = db.query("SELECT id,label,description,url,button_label,enabled,sort_order,subscription_template_id,method_type,details_json,reference_template,show_amount FROM portal_payment_links ORDER BY sort_order,id") or []
    plans = db.query(
        "SELECT id,name FROM subscription_templates ORDER BY LOWER(name),id"
    ) or []
    return {
        "enabled": bool(settings and settings["portal_payment_links_enabled"]),
        "experimental_enabled": bool(
            settings and settings["debug_mode"] and settings["portal_show_payment"]
        ),
        "currency": settings["subscription_currency"] if settings else "EUR",
        "links": [dict(row) | {"details": _json_details(row["details_json"])} for row in rows],
        "plans": [dict(row) for row in plans],
    }


def save_payment_links(db, form):
    labels = form.getlist("link_label")
    descriptions = form.getlist("link_description")
    urls = form.getlist("link_url")
    buttons = form.getlist("link_button_label")
    plan_values = form.getlist("link_subscription_template_id")
    method_types = form.getlist("link_method_type")
    identifiers = form.getlist("link_identifier")
    secondary_values = form.getlist("link_secondary_value")
    account_holders = form.getlist("link_account_holder")
    bics = form.getlist("link_bic")
    references = form.getlist("link_reference_template")
    show_amount_indexes = {int(value) for value in form.getlist("link_show_amount") if str(value).isdigit()}
    enabled_indexes = {int(value) for value in form.getlist("link_enabled") if str(value).isdigit()}
    valid_plan_ids = {
        int(row["id"]) for row in (
            db.query("SELECT id FROM subscription_templates") or []
        )
    }
    links, errors = [], []
    for index, label in enumerate(labels):
        label = str(label).strip()[:100]
        raw_url = str(urls[index] if index < len(urls) else "").strip()
        method_type = str(method_types[index] if index < len(method_types) else "custom")
        method_type = method_type if method_type in METHOD_TYPES else "custom"
        identifier = str(identifiers[index] if index < len(identifiers) else "").strip()[:254]
        secondary = str(secondary_values[index] if index < len(secondary_values) else "").strip()[:254]
        url = valid_external_url(raw_url) if raw_url else ""
        if not label and not raw_url and not identifier:
            continue
        if not label:
            errors.append("payment_link_label_required")
        if method_type == "custom" and not url:
            errors.append("payment_link_https_required")
        if method_type == "paypal_me" and not _paypal_username(identifier):
            errors.append("payment_paypal_required")
        if method_type in {"wero", "bank_transfer"} and not identifier:
            errors.append("payment_recipient_required")
        reference = str(references[index] if index < len(references) else "").strip()[:200]
        if _unknown_reference_variables(reference):
            errors.append("payment_reference_variables_invalid")
        raw_plan = str(plan_values[index] if index < len(plan_values) else "").strip()
        plan_id = int(raw_plan) if raw_plan.isdigit() and int(raw_plan) in valid_plan_ids else None
        details = {"identifier": identifier, "secondary_value": secondary, "account_holder": str(account_holders[index] if index < len(account_holders) else "").strip()[:150], "bic": str(bics[index] if index < len(bics) else "").strip()[:50]}
        links.append((label, str(descriptions[index] if index < len(descriptions) else "").strip()[:500] or None, url, str(buttons[index] if index < len(buttons) else "").strip()[:100] or None, int(index in enabled_indexes), index, plan_id, method_type, json.dumps(details, separators=(",", ":")), reference or None, int(index in show_amount_indexes)))
    if errors:
        return tuple(dict.fromkeys(errors))
    with db.transaction() as cursor:
        cursor.execute("UPDATE settings SET portal_payment_links_enabled=? WHERE id=1", (int(form.get("payment_links_enabled") == "1"),))
        cursor.execute("DELETE FROM portal_payment_links")
        cursor.executemany("INSERT INTO portal_payment_links(label,description,url,button_label,enabled,sort_order,subscription_template_id,method_type,details_json,reference_template,show_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?)", links)
    return ()


def load_applicable_payment_links(db, subscription_template_id, context=None):
    rows = db.query(
        "SELECT label,description,url,button_label,method_type,details_json,reference_template,show_amount FROM portal_payment_links "
        "WHERE (SELECT portal_payment_links_enabled FROM settings WHERE id=1)=1 "
        "AND (SELECT portal_show_payment FROM settings WHERE id=1)=1 "
        "AND (SELECT debug_mode FROM settings WHERE id=1)=1 "
        "AND enabled=1 AND (subscription_template_id IS NULL OR subscription_template_id=?) "
        "ORDER BY sort_order,id", (subscription_template_id,)
    ) or []
    result = []
    context = {key: str(value or "") for key, value in dict(context or {}).items() if key in REFERENCE_VARIABLES}
    for row in rows:
        item = dict(row)
        item["details"] = _json_details(item.pop("details_json", "{}"))
        item["reference"] = _render_reference(item.pop("reference_template", ""), context)
        if item["method_type"] == "custom" and not valid_external_url(item["url"]):
            continue
        if item["method_type"] == "paypal_me":
            username = _paypal_username(item["details"].get("identifier"))
            if not username:
                continue
            amount = context.get("amount", "") if item["show_amount"] else ""
            currency = context.get("currency", "") if amount else ""
            suffix = f"/{quote(amount + currency)}" if amount and currency else ""
            item["url"] = f"https://paypal.me/{quote(username)}{suffix}"
        result.append(item)
    return result


def _json_details(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _paypal_username(value):
    text = str(value or "").strip().rstrip("/")
    if "/" in text:
        parsed = urlsplit(text if "://" in text else "https://" + text)
        if parsed.hostname not in {"paypal.me", "www.paypal.me"}:
            return None
        text = parsed.path.strip("/").split("/")[0]
    return text if re.fullmatch(r"[A-Za-z0-9._-]{2,100}", text) else None


def _unknown_reference_variables(template):
    return {name for name in re.findall(r"\{([^{}]+)\}", template or "") if name not in REFERENCE_VARIABLES}


def _render_reference(template, context):
    return re.sub(r"\{([^{}]+)\}", lambda match: context.get(match.group(1), match.group(0)), str(template or ""))
