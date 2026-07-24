import time

from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_enforcer_config import HOUSEHOLD_MEDIA_GRACE_SECONDS
from core.stream_media_transition import ip_grace_key, is_coherent_media_transition


logger = get_logger("stream_enforcer")
IP_GRACE_CACHE: dict[str, float] = {}


def should_grace_coherent_ip_switch(policy: dict, user_key, sessions: list[dict], ips: set, max_ips: int) -> bool:
    now = time.time()
    for key in list(IP_GRACE_CACHE):
        if now - float(IP_GRACE_CACHE.get(key) or 0) > HOUSEHOLD_MEDIA_GRACE_SECONDS:
            IP_GRACE_CACHE.pop(key, None)
    if len(ips) > max_ips + 1 or len(sessions) < 2 or not is_coherent_media_transition(sessions):
        return False
    key = ip_grace_key(int(policy.get("id") or 0), user_key, sessions)
    first_seen = IP_GRACE_CACHE.get(key)
    if not first_seen:
        IP_GRACE_CACHE[key] = now
        logger.info("[max_ips_grace] coherent media switch detected | policy=%s | user=%s | ips=%s | max_ips=%s | grace=%ss", policy.get("id"), user_key, sorted(ips), max_ips, HOUSEHOLD_MEDIA_GRACE_SECONDS)
        return True
    elapsed = now - float(first_seen)
    if elapsed <= HOUSEHOLD_MEDIA_GRACE_SECONDS:
        if is_debug_mode_enabled():
            logger.debug("[max_ips_grace] still inside grace window | policy=%s | user=%s | elapsed=%ss/%ss", policy.get("id"), user_key, int(elapsed), HOUSEHOLD_MEDIA_GRACE_SECONDS)
        return True
    IP_GRACE_CACHE.pop(key, None)
    logger.warning("[max_ips_grace] grace expired, enforcing violation | policy=%s | user=%s | ips=%s | max_ips=%s", policy.get("id"), user_key, sorted(ips), max_ips)
    return False
