from __future__ import annotations


def load_recent_monitoring_events(db, tab, limit=30):
    if tab not in {"overview", "activity"}:
        return []
    return db.query(
        """
        SELECT e.id, s.name AS server_name, e.provider, e.event_type,
          e.ts, e.media_type, e.title, mu.username AS username,
          COALESCE(
            json_extract(e.payload_json, '$.grandparent_title'),
            json_extract(e.payload_json, '$.grandparentTitle')
          ) AS series_title,
          COALESCE(
            json_extract(e.payload_json, '$.season_number'),
            json_extract(e.payload_json, '$.ParentIndexNumber')
          ) AS season_number,
          COALESCE(
            json_extract(e.payload_json, '$.episode_number'),
            json_extract(e.payload_json, '$.IndexNumber')
          ) AS episode_number
        FROM media_events e
        JOIN servers s ON s.id = e.server_id
        LEFT JOIN media_users mu ON mu.id = e.media_user_id
        ORDER BY e.ts DESC
        LIMIT ?
        """,
        (int(limit),),
    ) or []
