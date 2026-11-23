import time

from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_enforcer_config import HOUSEHOLD_MEDIA_GRACE_SECONDS
from core.stream_media_transition import is_coherent_media_transition
from core.policy_transition_grace import _switch_pair, _timestamp


logger = get_logger("stream_enforcer")
IP_GRACE_CACHE: dict[str, dict[str, float]] = {}


def should_grace_coherent_ip_switch(policy: dict, user_key, sessions: list[dict], ips: set, max_ips: int) -> bool:
    now = time.time()
    for key in list(IP_GRACE_CACHE):
        # Keep expired deadlines through enforcement and its recheck. Removing
        # them at the grace deadline restarted the grace forever.
        if now - IP_GRACE_CACHE[key]["last_seen"] > HOUSEHOLD_MEDIA_GRACE_SECONDS:
            IP_GRACE_CACHE.pop(key, None)
    if len(ips) <= max_ips:
        prefix = f"policy:{int(policy.get('id') or 0)}|user:{user_key}|"
        for key in list(IP_GRACE_CACHE):
            if key.startswith(prefix):
                IP_GRACE_CACHE.pop(key, None)
        return False
    if max_ips <= 0 or len(ips) > max_ips + 1 or len(sessions) < 2:
        return False
    # New episodes/session keys must not renew a continuously observed excess.
    key = f"policy:{int(policy.get('id') or 0)}|user:{user_key}|overlap"
    entry = IP_GRACE_CACHE.get(key)
    if entry is None:
        coherent = is_coherent_media_transition(sessions)
        recent_switch = any(
            a.get("ip") != b.get("ip") and _switch_pair(a, b)
            and any(0 <= now - stamp < HOUSEHOLD_MEDIA_GRACE_SECONDS
                    for item in (a, b) if (stamp := _timestamp(item.get("started_at"))) is not None)
            for index, a in enumerate(sessions) for b in sessions[index + 1:]
        )
        if not coherent and not recent_switch:
            return False
        IP_GRACE_CACHE[key] = {"first_seen": now, "last_seen": now}
        logger.info("[max_ips_grace] coherent media switch detected | policy=%s | user=%s | ips=%s | max_ips=%s | grace=%ss", policy.get("id"), user_key, sorted(ips), max_ips, HOUSEHOLD_MEDIA_GRACE_SECONDS)
        return True
    entry["last_seen"] = now
    elapsed = now - entry["first_seen"]
    if elapsed < HOUSEHOLD_MEDIA_GRACE_SECONDS:
        if is_debug_mode_enabled():
            logger.debug("[max_ips_grace] still inside grace window | policy=%s | user=%s | elapsed=%ss/%ss", policy.get("id"), user_key, int(elapsed), HOUSEHOLD_MEDIA_GRACE_SECONDS)
        return True
    logger.warning("[max_ips_grace] grace expired, enforcing violation | policy=%s | user=%s | ips=%s | max_ips=%s", policy.get("id"), user_key, sorted(ips), max_ips)
    return False
