def get_days_before(template_row: dict | None, fallback: int | None) -> int | None:
    if not template_row or template_row.get("days_before") is None:
        return fallback
    try:
        return int(template_row["days_before"])
    except Exception:
        return fallback


def get_days_after(template_row: dict | None) -> int | None:
    if not template_row or template_row.get("days_after") is None:
        return None
    try:
        return int(template_row["days_after"])
    except Exception:
        return None


def safe_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def subscription_scope_rank(template_row: dict, user_subscription_template_id: int | None) -> int:
    scope = (template_row.get("subscription_scope") or "none").strip().lower()
    template_subscription_id = safe_int(template_row.get("subscription_template_id"))
    if scope == "specific":
        if user_subscription_template_id is None:
            return -1
        return 3 if template_subscription_id == user_subscription_template_id else -1
    if scope == "all":
        return 2
    return 1


def provider_rank(template_row: dict, providers: list[str]) -> int:
    template_provider = (template_row.get("trigger_provider") or "all").strip().lower()
    normalized = [provider for provider in (providers or []) if provider in ("plex", "jellyfin")]
    if template_provider in normalized:
        return 3
    if template_provider == "all":
        return 2
    if template_provider in ("plex", "jellyfin"):
        return 1
    return -1


def match_before_window(days_left: int, current_value: int | None, all_values: list[int], after_values: list[int] | None = None) -> bool:
    if current_value is None:
        return False
    if days_left < 0:
        if current_value != 0:
            return False
        overdue_days = -days_left
        future_after_values = sorted(v for v in (after_values or []) if v is not None and int(v) >= 0)
        next_after = future_after_values[0] if future_after_values else None
        return next_after is None or overdue_days < next_after
    lower_values = sorted((v for v in all_values if v < current_value), reverse=True)
    lower_bound = lower_values[0] if lower_values else -1
    return lower_bound < days_left <= current_value


def match_after_window(days_left: int, current_value: int | None, all_values: list[int]) -> bool:
    if current_value is None or days_left >= 0:
        return False
    overdue_days = -days_left
    higher_values = sorted(v for v in all_values if v > current_value)
    upper_bound = higher_values[0] if higher_values else None
    return overdue_days >= current_value if upper_bound is None else current_value <= overdue_days < upper_bound


def pick_expiration_template(days_left: int, templates: list[dict], providers: list[str], user_subscription_template_id: int | None) -> tuple[dict, str, int | None] | None:
    normalized_providers = [provider for provider in (providers or []) if provider in ("plex", "jellyfin")]
    applicable = []
    for template in templates:
        sub_rank = subscription_scope_rank(template, user_subscription_template_id)
        prov_rank = provider_rank(template, normalized_providers)
        if sub_rank >= 0 and prov_rank >= 0:
            applicable.append({**template, "_sub_rank": sub_rank, "_prov_rank": prov_rank})
    if not applicable:
        return None

    before_values = [value for value in (get_days_before(tpl, None) for tpl in applicable) if value is not None]
    after_values = [value for value in (get_days_after(tpl) for tpl in applicable) if value is not None]
    matches = []
    for template in applicable:
        before_value = get_days_before(template, None)
        after_value = get_days_after(template)
        if (
            before_value is not None
            and match_before_window(days_left, before_value, before_values, after_values)
        ) or (
            after_value is not None
            and match_after_window(days_left, after_value, after_values)
        ):
            matches.append(template)
    if not matches:
        return None

    matches.sort(key=lambda item: (-int(item["_sub_rank"]), -int(item["_prov_rank"]), int(item["id"])))
    best = matches[0]
    template_provider = (best.get("trigger_provider") or "all").strip().lower()
    if template_provider in normalized_providers:
        queue_provider = template_provider
    elif normalized_providers:
        queue_provider = normalized_providers[0]
    elif template_provider in ("plex", "jellyfin"):
        queue_provider = template_provider
    else:
        queue_provider = "plex"
    best.pop("_sub_rank", None)
    best.pop("_prov_rank", None)
    return best, queue_provider, None
