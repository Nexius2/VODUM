from typing import Optional


SERVER_BOUND_ACTORS = {"server", "4k", "bitrate", "device"}


def select_rechecked_violation(previous: dict, candidates: list[dict]) -> Optional[dict]:
    target_user = previous["target_user"]
    same_actor = []
    for candidate in candidates:
        if candidate["kind"] != previous["kind"] or candidate["target_user"] != target_user:
            continue
        same_actor.append(candidate)
        if candidate["server_id"] == previous["server_id"]:
            return candidate
    synthetic_actor = str(target_user[1] if len(target_user) > 1 else "") in SERVER_BOUND_ACTORS
    if same_actor and not synthetic_actor:
        return same_actor[0]
    return None
