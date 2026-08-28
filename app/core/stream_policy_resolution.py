from __future__ import annotations

from core.stream_policy_scope import policy_applies
from core.stream_policy_utils import loads_json


SUBSCRIPTION_ACCESS_RULES = frozenset(
    {"max_streams_per_user", "max_streams_per_ip", "max_ips_per_user"}
)


def _rule(policy: dict) -> dict:
    return loads_json(policy.get("rule_value_json"))


def is_subscription_policy(policy: dict, subscription_template_id=None) -> bool:
    rule = _rule(policy)
    if not rule.get("locked") or not rule.get("subscription_template_id"):
        return False
    if subscription_template_id is None:
        return True
    try:
        return int(rule["subscription_template_id"]) == int(subscription_template_id)
    except (TypeError, ValueError):
        return False


def _specificity(policy: dict) -> tuple[int, int, int]:
    scope_type = policy.get("scope_type")
    if scope_type == "user":
        scope_rank = 3
    elif scope_type == "server" or policy.get("server_id") is not None:
        scope_rank = 2
    else:
        scope_rank = 1
    return (
        scope_rank,
        1 if policy.get("server_id") is not None else 0,
        1 if policy.get("provider") else 0,
    )


def effective_policies_for_session(policies: list[dict], session: dict) -> list[dict]:
    """Resolve policy inheritance for one playback session.

    A matching subscription snapshot owns the complete streaming-access bundle.
    Therefore an omitted rule in that bundle means "unlimited", rather than
    inheritance from a server/global policy. Manual user policies remain at the
    same functional level and are intentionally retained.
    """
    applicable = [policy for policy in policies if policy_applies(policy, session)]
    subscription_template_id = session.get("subscription_template_id")
    subscription_bundle = [
        policy
        for policy in applicable
        if policy.get("rule_type") in SUBSCRIPTION_ACCESS_RULES
        and is_subscription_policy(policy, subscription_template_id)
        and subscription_template_id is not None
    ]
    if subscription_bundle:
        applicable = [
            policy
            for policy in applicable
            if policy.get("rule_type") not in SUBSCRIPTION_ACCESS_RULES
            or policy.get("scope_type") == "user"
        ]

    resolved: list[dict] = []
    for rule_type in {policy.get("rule_type") for policy in applicable}:
        same_rule = [policy for policy in applicable if policy.get("rule_type") == rule_type]
        best = max((_specificity(policy) for policy in same_rule), default=None)
        resolved.extend(policy for policy in same_rule if _specificity(policy) == best)
    return resolved


def sessions_for_policy(
    policy: dict, policies: list[dict], sessions: list[dict]
) -> list[dict]:
    policy_id = policy.get("id")
    return [
        session
        for session in sessions
        if any(candidate.get("id") == policy_id for candidate in effective_policies_for_session(policies, session))
    ]
