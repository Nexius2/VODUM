from __future__ import annotations
from typing import Any, Dict, List, Optional

def compute_session_events(prev: Optional[Dict[str, Any]], cur: Optional[Dict[str, Any]]) -> List[str]:
    if prev is None and cur is not None:
        return ["start"]
    if prev is not None and cur is None:
        return ["stop"]
    if prev is None or cur is None:
        return []

    prev_state = (prev.get("state") or "unknown").lower()
    cur_state = (cur.get("state") or "unknown").lower()

    if prev_state == cur_state:
        return []

    if cur_state == "paused":
        return ["pause"]
    if prev_state == "paused" and cur_state == "playing":
        return ["resume"]

    return ["state_change"]
