MONITORING_TASKS = ("monitor_enqueue_refresh", "media_jobs_worker")
SYNC_TASKS_BY_PROVIDER = {
    "plex": ("sync_plex",),
    "jellyfin": ("sync_jellyfin",),
}


def enabled_from_count(value) -> int:
    try:
        return 1 if int(value or 0) > 0 else 0
    except (TypeError, ValueError):
        return 0


def stream_enforcer_should_enable(policy_count, subscription_count) -> int:
    return enabled_from_count(policy_count) if enabled_from_count(subscription_count) else 0
