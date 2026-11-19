import json

from core.monitoring.ip_location import load_ip_coordinates, parse_stream_ip
from core.monitoring.mappers import apply_playback_username
from db_manager import isolated_read_operation


@isolated_read_operation
def _load_playbacks(db, live_only, live_window_seconds, server_id, instant):
    return db.query(
        """
        WITH playbacks AS (
            SELECT id, server_id, provider, media_user_id, external_user_id, session_key, media_key, started_at,
                   ip, title, grandparent_title,
                   CASE WHEN :instant IS NULL THEN last_seen_at ELSE started_at END AS seen_at,
                   1 AS current,
                   CASE WHEN :instant IS NULL AND datetime(last_seen_at) >= datetime('now', :window)
                        AND LOWER(COALESCE(state, '')) <> 'stopped'
                        THEN LOWER(COALESCE(state, '')) ELSE 'offline' END AS state
            FROM media_sessions
            WHERE :instant IS NULL OR (
                datetime(started_at) <= datetime(:instant, 'unixepoch')
                AND datetime(last_seen_at) >= datetime(:instant, 'unixepoch')
            )
            UNION ALL
            SELECT id, server_id, provider, media_user_id, external_user_id, session_key, media_key, started_at,
                   ip, title, grandparent_title,
                   CASE WHEN :instant IS NULL THEN stopped_at ELSE started_at END, 0, 'offline'
            FROM media_session_history
            WHERE (:instant IS NULL AND NOT :live_only)
               OR (:instant IS NOT NULL AND datetime(started_at) <= datetime(:instant, 'unixepoch')
                   AND datetime(stopped_at) >= datetime(:instant, 'unixepoch'))
        ), identified AS (
            SELECT p.*, mu.id AS account_id, mu.avatar, vu.id AS vodum_user_id,
                   COALESCE(NULLIF(TRIM(vu.username), ''), mu.username) AS username,
                   CASE WHEN vu.id IS NOT NULL THEN 'user:' || vu.id
                        WHEN NULLIF(TRIM(p.external_user_id), '') IS NOT NULL
                             THEN p.provider || ':' || p.external_user_id
                        ELSE 'account:' || mu.id END AS identity
            FROM playbacks p
            LEFT JOIN media_users mu ON mu.id = COALESCE(p.media_user_id, (
                SELECT id FROM media_users
                WHERE server_id = p.server_id AND type = p.provider
                  AND external_user_id = p.external_user_id AND TRIM(external_user_id) <> ''
            ))
            LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
            WHERE (:server_id IS NULL OR p.server_id = :server_id)
              AND (NOT :live_only OR :instant IS NOT NULL OR p.state <> 'offline')
              AND (mu.id IS NOT NULL OR NULLIF(TRIM(p.external_user_id), '') IS NOT NULL)
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                       PARTITION BY identity
                       ORDER BY (:playing_only AND state = 'playing') DESC,
                                julianday(seen_at) DESC, current DESC, id DESC
                   ) AS playback_rank,
                   MAX(state <> 'offline') OVER (PARTITION BY identity) AS online,
                   SUM(state = 'playing') OVER (PARTITION BY identity) AS active,
                   COUNT(*) OVER (PARTITION BY identity) AS sessions
            FROM identified
        )
        SELECT r.*, s.name AS server_name, COALESCE(ms.raw_json, h.raw_json) AS raw_json,
               COALESCE(ms.client_name, h.client_name) AS client, l.name AS library,
               ms.progress_ms, ms.duration_ms,
               CASE WHEN :instant IS NOT NULL AND NULLIF(r.session_key, '') IS NOT NULL THEN (
                   SELECT e.payload_json
                   FROM media_events e
                   WHERE e.server_id = r.server_id AND e.provider = r.provider
                     AND e.session_key = r.session_key AND e.media_key IS r.media_key
                     AND (e.media_user_id IS NULL OR r.media_user_id IS NULL OR e.media_user_id = r.media_user_id)
                     AND (e.external_user_id IS NULL OR r.external_user_id IS NULL
                          OR e.external_user_id = r.external_user_id)
                     AND e.event_type IN ('start', 'pause', 'resume', 'state_change')
                     AND json_valid(e.payload_json)
                     AND e.ts >= date(r.started_at)
                     AND e.ts < date(:instant, 'unixepoch', '+1 day')
                     AND julianday(e.ts) BETWEEN julianday(r.started_at) AND julianday(:instant, 'unixepoch')
                   ORDER BY julianday(e.ts) DESC, e.id DESC LIMIT 1
               ) END AS historical_event,
               CASE WHEN :instant IS NULL AND :risk_enabled THEN (
                   SELECT urr.risk_level FROM usage_risk_recommendations urr
                   WHERE urr.vodum_user_id = r.vodum_user_id AND urr.status IN ('detected', 'notified')
                   ORDER BY urr.last_detected_at DESC, urr.id DESC LIMIT 1
               ) END AS risk_level
        FROM ranked r
        JOIN servers s ON s.id = r.server_id
        LEFT JOIN media_sessions ms ON r.current = 1 AND ms.id = r.id
        LEFT JOIN media_session_history h ON r.current = 0 AND h.id = r.id
        LEFT JOIN libraries l ON l.server_id = r.server_id
            AND l.section_id = COALESCE(ms.library_section_id, h.library_section_id)
        WHERE playback_rank = 1
        ORDER BY julianday(seen_at) DESC
        """,
        {
            "window": f"-{int(live_window_seconds)} seconds",
            "live_only": live_only,
            "playing_only": live_only,
            "server_id": server_id,
            "instant": instant,
            "risk_enabled": bool(db.query_one(
                "SELECT id FROM settings WHERE id = 1 AND usage_risk_enabled = 1"
            )) if instant is None else False,
        },
    )


def load_monitoring_locations(db, *, live_only, live_window_seconds, server_id=None,
                              instant=None, playing_only=False, country=""):
    rows = _load_playbacks(db, live_only or playing_only, live_window_seconds, server_id, instant)
    rows = [row for row in rows if not playing_only or instant is not None or row["active"]]
    observations = []
    for row in rows:
        event = json.loads(row["historical_event"]) if row["historical_event"] else {}
        if not isinstance(event, dict):
            event = {}
        event_ip = event.get("ip")
        address = parse_stream_ip(event_ip) if isinstance(event_ip, str) else None
        if address is None and (instant is None or not row["current"]):
            address = parse_stream_ip(row["ip"])
        observations.append((row, str(address) if address is not None else None, event))
    coordinates = load_ip_coordinates(ip for _, ip, _ in observations if ip)
    points, countries, cities = [], set(), set()
    online, active = 0, 0
    country_options = set()
    for row, ip, event in observations:
        geo = coordinates.get(ip)
        if geo and geo[4]:
            country_options.add(geo[4])
        if country and (not geo or geo[4] != country):
            continue
        online += 1 if instant is not None else row["online"]
        active += row["sessions"] if instant is not None else row["active"]
        if not geo:
            continue
        (latitude, longitude), location, city, region, code = geo
        if code:
            countries.add(code)
        if city and code:
            cities.add((code, region, city))
        playback = dict(row)
        apply_playback_username(playback)
        title = " · ".join(dict.fromkeys(filter(None, (row["grandparent_title"], row["title"]))))
        state = "offline"
        if instant is not None:
            state = {
                "playing": "recorded_playing", "paused": "recorded_paused",
            }.get(str(event.get("state") or "").lower(), "recorded")
        elif row["state"] == "playing":
            state = "playing"
        elif row["online"]:
            state = "paused" if row["state"] == "paused" else "online"
        progress = None
        if row["state"] != "offline" and row["duration_ms"] and row["progress_ms"] is not None:
            progress = min(100, max(0, round(100 * row["progress_ms"] / row["duration_ms"])))
        points.append({
            "identity": row["identity"],
            "latitude": latitude,
            "longitude": longitude,
            "location": location,
            "username": playback["username"] or row["external_user_id"],
            "title": title,
            "seen_at": row["seen_at"],
            "state": state,
            "server": row["server_name"],
            "provider": "Plex" if row["provider"] == "plex" else "Jellyfin",
            "client": row["client"],
            "library": row["library"],
            "progress": progress,
            "account_id": row["account_id"],
            "avatar": row["avatar"] if (row["avatar"] or "").startswith("/static/") else None,
            "provider_avatar": bool(row["avatar"] and row["account_id"]),
            "ip": ip,
            "risk_level": row["risk_level"] if row["risk_level"] in {"low", "medium", "high"} else None,
        })
    return {
        "points": points,
        "stats": {"countries": len(countries), "cities": len(cities), "online": online, "active": active},
        "countries": sorted(country_options | ({country} if country else set())),
    }
