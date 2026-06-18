from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.policy_transition_grace import (  # noqa: E402
    reset_stream_transition_grace,
    should_defer_stream_violation,
)


def session(key: str, title: str, started: float) -> dict:
    return {
        "session_key": key,
        "media_type": "episode",
        "grandparent_title": "Example Show",
        "parent_title": "Season 1",
        "title": title,
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
    }


now = 2_000_000_000.0
same_episode = [
    session("tv", "Episode 4", now - 900),
    session("pc", "Episode 8", now - 600),
    session("mobile", "Episode 4", now - 20),
]

reset_stream_transition_grace()
assert should_defer_stream_violation(
    policy_id=7, user_key=(12, "user", None), sessions=same_episode,
    limit=2, current_count=3, now=now,
)
assert should_defer_stream_violation(
    policy_id=7, user_key=(12, "user", None), sessions=same_episode,
    limit=2, current_count=3, now=now + 299,
)
assert not should_defer_stream_violation(
    policy_id=7, user_key=(12, "user", None), sessions=same_episode,
    limit=2, current_count=3, now=now + 300,
)

reset_stream_transition_grace()
different_content = [
    session("tv", "Episode 1", now - 20),
    session("pc", "Episode 2", now - 20),
    session("mobile", "Episode 3", now - 20),
]
assert not should_defer_stream_violation(
    policy_id=7, user_key=(12, "user", None), sessions=different_content,
    limit=2, current_count=3, now=now,
)
assert not should_defer_stream_violation(
    policy_id=7, user_key=(12, "user", None), sessions=same_episode + [session("tablet", "Episode 4", now - 10)],
    limit=2, current_count=4, now=now,
)

print("OK - probable one-stream device switches receive exactly five minutes of grace.")
