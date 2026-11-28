DEFAULT_SUBSCRIPTION_TEMPLATES = [
    (
        "base sub",
        "2 streams / Same IP",
        365,
        None,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2}},{"rule_type":"max_streams_per_ip","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
        0,
        0,
    ),
    (
        "Family sub",
        "4 streams",
        365,
        None,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":4}}]',
        0,
        0,
    ),
    (
        "Plus sub",
        "3 streams / 2 IP",
        365,
        None,
        0,
        0,
        '[{"rule_type":"max_streams_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":3}},{"rule_type":"max_ips_per_user","provider":null,"server_id":null,"is_enabled":1,"priority":100,"rule":{"selector":"kill_newest","warn_title":"Streaming limit reached","warn_text":"You have reached the allowed number of simultaneous streams","max":2,"allow_local_ip":true}}]',
        0,
        0,
    ),
    ("Lifetime sub", "Lifetime access", 0, None, 0, 0, '[]', 1, 1),
]


def restore_default_subscription_templates(db) -> int:
    from core.default_data_i18n import bundled_subscription_texts, subscription_name_variants

    try:
        settings = db.query_one("SELECT default_language FROM settings WHERE id = ?", (1,))
        language = dict(settings).get("default_language") if settings else None
    except Exception:
        language = None
    restored = 0
    for index, (name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json, is_lifetime, hide_from_portal) in enumerate(DEFAULT_SUBSCRIPTION_TEMPLATES):
        names = [name] + sorted(subscription_name_variants(index) - {name})
        if any(
            db.query_one("SELECT id FROM subscription_templates WHERE name = ?", (candidate,))
            for candidate in names
        ):
            continue
        name, notes = bundled_subscription_texts(index, language) or (name, notes)
        db.execute(
            """
            INSERT INTO subscription_templates(
              name,
              notes,
              duration_days,
              subscription_value,
              is_default,
              is_enabled,
              policies_json,
              is_lifetime,
              hide_from_portal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, notes, duration_days, subscription_value, is_default, is_enabled, policies_json, is_lifetime, hide_from_portal),
        )
        restored += 1
    return restored
