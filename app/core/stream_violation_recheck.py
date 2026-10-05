from typing import Optional


SERVER_BOUND_ACTORS = {"server", "4k", "bitrate", "device"}


def select_rechecked_violation(previous: dict, candidates: list[dict]) -> Optional[dict]:
    target_user = previous["target_user"]
    same_actor = []
    for candidate in candidates:
        candidate_user = candidate["target_user"]
        actor_matches = (
            candidate_user[0] == target_user[0]
            if candidate_user[0] is not None and target_user[0] is not None
            else candidate_user == target_user
        )
        if candidate["kind"] != previous["kind"] or not actor_matches:
            continue
        same_actor.append(candidate)
        if candidate["server_id"] == previous["server_id"]:
            return candidate
    synthetic_actor = str(target_user[1] if len(target_user) > 1 else "") in SERVER_BOUND_ACTORS
    if same_actor and not synthetic_actor and target_user[0] is not None:
        return same_actor[0]
    return None
