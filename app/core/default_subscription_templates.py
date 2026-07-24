DEFAULT_SUBSCRIPTION_TEMPLATES = [
    (
        "base sub",
        "2 streams / Same IP",
        365,
        70,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}},{"rule_type":"max_streams_per_ip","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
    ),
    (
        "Family sub",
        "4 streams",
        365,
        200,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":4,"allow_local_ip":true}}]',
    ),
    (
        "Plus sub",
        "3 streams / 2 IP",
        365,
        120,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":3,"allow_local_ip":true}},{"rule_type":"max_ips_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
    ),
]


def restore_default_subscription_templates(db) -> int:
    restored = 0
    for name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json in DEFAULT_SUBSCRIPTION_TEMPLATES:
        existing = db.query_one(
            "SELECT id FROM subscription_templates WHERE name = ?",
            (name,),
        )
        if existing:
            continue
        db.execute(
            """
            INSERT INTO subscription_templates(
              name,
              notes,
              duration_days,
              subscription_value,
              is_default,
              is_enabled,
              policies_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json),
        )
        restored += 1
    return restored
