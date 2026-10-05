from typing import Dict, List, Optional
import json

from core.stream_policy_utils import loads_json
from logging_utils import get_logger

logger = get_logger("stream_enforcer")


def load_user_stream_overrides(db) -> Dict[int, int]:
    overrides = {}
    try:
        rows = db.query("""
            SELECT id, max_streams_override FROM vodum_users
            WHERE max_streams_override IS NOT NULL AND max_streams_override > 0
        """)
        for row in rows:
            try:
                value = int(row["max_streams_override"])
                if value > 0:
                    overrides[int(row["id"])] = value
            except Exception:
                continue
    except Exception:
        return {}
    return overrides


def load_enabled_policies(db) -> List[dict]:
    rows = db.query("""
        SELECT id, scope_type, scope_id, provider, server_id, is_enabled,
               priority, rule_type, rule_value_json, created_at, updated_at
        FROM stream_policies WHERE is_enabled=1 ORDER BY priority ASC, id ASC
    """)
    policies = []
    for row in rows:
        policy = dict(row)
        try:
            rule = json.loads(policy.get("rule_value_json") or "{}")
            if not isinstance(rule, dict):
                raise ValueError("rule must be a JSON object")
            rule_type = policy.get("rule_type")
            if rule_type in {"max_streams_per_user", "max_streams_per_ip", "max_ips_per_user", "max_transcodes_global"}:
                if int(rule.get("max", 1)) < 0:
                    raise ValueError("max must be nonnegative")
            elif rule_type == "max_bitrate_kbps":
                if int(rule.get("max_kbps", 0)) < 0:
                    raise ValueError("max_kbps must be nonnegative")
        except (TypeError, ValueError, OverflowError):
            logger.error("Invalid enabled stream policy skipped: policy_id=%s rule_type=%s", policy.get("id"), policy.get("rule_type"))
            continue
        policies.append(policy)
    return policies


def load_live_sessions(db, window_seconds: int, stable_seconds: int) -> List[dict]:
    rows = db.query("""
        SELECT ms.server_id, LOWER(TRIM(s.type)) AS provider, ms.session_key,
          ms.media_user_id, ms.external_user_id, mu.vodum_user_id,
          vu.subscription_template_id,
          mu.username AS media_username, ms.media_key, ms.media_type, ms.title,
          ms.grandparent_title, ms.parent_title, ms.state, ms.progress_ms,
          ms.duration_ms, ms.is_transcode, ms.bitrate, ms.device, ms.client_name,
          ms.client_product, ms.ip, ms.started_at, ms.last_seen_at, ms.raw_json
        FROM media_sessions ms
        JOIN servers s ON s.id = ms.server_id
        LEFT JOIN media_users mu ON mu.id = ms.media_user_id
        LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
          AND COALESCE(s.status, '') != 'down'
          AND (s.cooldown_until IS NULL OR s.cooldown_until <= CURRENT_TIMESTAMP)
          AND datetime(ms.last_seen_at) >= datetime('now', ?)
          AND COALESCE(ms.missing_count, 0) = 0
          AND datetime(COALESCE(ms.started_at, ms.last_seen_at)) <= datetime('now', ?)
        ORDER BY ms.server_id
    """, (f"-{int(window_seconds)} seconds", f"-{int(stable_seconds)} seconds"))
    sessions = []
    for row in rows:
        session = dict(row)
        session["_parsed_raw_json"] = loads_json(session.get("raw_json"))
        sessions.append(session)
    return sessions


def load_server(db, server_id: int) -> Optional[dict]:
    row = db.query_one("""
        SELECT id, type, url, local_url, public_url, token, server_identifier, settings_json
        FROM servers WHERE id=? LIMIT 1
    """, (server_id,))
    return dict(row) if row else None
