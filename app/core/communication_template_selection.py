from typing import Dict, Iterable, List


def _safe_nullable_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def subscription_scope_rank(template: Dict, subscription_template_id: int | None) -> int:
    scope = (template.get("subscription_scope") or "none").strip().lower()
    expected_id = _safe_nullable_int(template.get("subscription_template_id"))
    if scope == "specific":
        if subscription_template_id is None:
            return -1
        return 3 if expected_id == subscription_template_id else -1
    if scope == "all":
        return 2
    return 1


def provider_rank(template: Dict, provider: str) -> int:
    expected = (template.get("trigger_provider") or "all").strip().lower()
    if expected == provider:
        return 2
    if expected == "all":
        return 1
    return -1


def expiration_change_direction_rank(template: Dict, direction: str | None) -> int:
    if not direction:
        return 1
    expected = (template.get("expiration_change_direction") or "all").strip().lower()
    if expected == direction:
        return 2
    if expected == "all":
        return 1
    return -1


def _slot_key(template: Dict, trigger_event: str):
    if trigger_event == "expiration":
        return trigger_event, template.get("days_before"), template.get("days_after")
    if trigger_event in ("user_creation", "pending_invite_reminder", "referral_reward"):
        return trigger_event, template.get("days_after")
    if trigger_event == "expiration_change":
        return trigger_event, template.get("expiration_change_direction") or "all"
    return trigger_event, template.get("days_before"), template.get("days_after")


def select_best_templates(
    rows: Iterable,
    *,
    trigger_event: str,
    provider: str,
    subscription_template_id: int | None,
    expiration_change_direction: str | None = None,
) -> List[Dict]:
    candidates = []
    for row in rows:
        template = dict(row)
        sub_rank = subscription_scope_rank(template, subscription_template_id)
        prov_rank = provider_rank(template, provider)
        if sub_rank < 0 or prov_rank < 0:
            continue
        direction_rank = 0
        if trigger_event == "expiration_change":
            direction_rank = expiration_change_direction_rank(template, expiration_change_direction)
            if direction_rank < 0:
                continue
        template["_sub_rank"] = sub_rank
        template["_prov_rank"] = prov_rank
        template["_dir_rank"] = direction_rank
        candidates.append(template)

    candidates.sort(
        key=lambda item: (
            -int(item["_sub_rank"]),
            -int(item["_prov_rank"]),
            -int(item.get("_dir_rank", 0)),
            int(item["id"]),
        )
    )
    best_by_slot = {}
    for template in candidates:
        slot = _slot_key(template, trigger_event)
        if slot in best_by_slot:
            continue
        cleaned = dict(template)
        cleaned.pop("_sub_rank", None)
        cleaned.pop("_prov_rank", None)
        cleaned.pop("_dir_rank", None)
        best_by_slot[slot] = cleaned

    output = list(best_by_slot.values())
    output.sort(
        key=lambda item: (
            999999 if item.get("days_before") is None else int(item.get("days_before") or 0),
            999999 if item.get("days_after") is None else int(item.get("days_after") or 0),
            int(item["id"]),
        )
    )
    return output
