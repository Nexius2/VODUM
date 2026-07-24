USAGE_RISK_SUBJECT = "A more suitable subscription may be available"
USAGE_RISK_BODY = (
    "Hello {username},\n\n"
    "We noticed that your usage regularly reaches the limits of your current subscription.\n\n"
    "Current subscription: {current_subscription}\n"
    "Suggested subscription: {suggested_subscription}\n\n"
    "This is only a recommendation to improve your experience and avoid blocked playback.\n\n"
    "Best regards,\n"
    "{brand_name}\n"
)


def ensure_usage_risk_template(conn, cursor) -> None:
    cursor.execute("""
        SELECT id, key, enabled, subject, body
        FROM comm_templates
        WHERE key = 'usage_risk_upgrade_suggestion'
           OR trigger_event = 'usage_risk_upgrade_suggestion'
           OR LOWER(name) = 'usage risk upgrade suggestion'
        ORDER BY
            enabled DESC,
            CASE
                WHEN COALESCE(subject, '') <> ? OR COALESCE(body, '') <> ? THEN 0
                ELSE 1
            END,
            id ASC
        LIMIT 1
    """, (USAGE_RISK_SUBJECT, USAGE_RISK_BODY))
    row = cursor.fetchone()

    if row:
        template_id = int(row[0])
        cursor.execute("""
            UPDATE comm_templates
            SET key = 'usage_risk_upgrade_suggestion_duplicate_' || id,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = 'usage_risk_upgrade_suggestion' AND id <> ?
        """, (template_id,))
        cursor.execute("""
            UPDATE comm_templates
            SET key = 'usage_risk_upgrade_suggestion',
                trigger_event = 'usage_risk_upgrade_suggestion',
                trigger_provider = 'all',
                expiration_change_direction = 'all',
                subscription_scope = 'all',
                subscription_template_id = NULL,
                days_before = NULL,
                days_after = 0,
                subject = CASE WHEN subject IS NULL OR TRIM(subject) = '' THEN ? ELSE subject END,
                body = CASE WHEN body IS NULL OR TRIM(body) = '' THEN ? ELSE body END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (USAGE_RISK_SUBJECT, USAGE_RISK_BODY, template_id))
    else:
        cursor.execute("""
            INSERT INTO comm_templates(
                key, name, enabled, trigger_event, trigger_provider,
                expiration_change_direction, subscription_scope,
                subscription_template_id, days_before, days_after,
                subject, body, created_at, updated_at
            ) VALUES(
                'usage_risk_upgrade_suggestion', 'Usage risk upgrade suggestion',
                0, 'usage_risk_upgrade_suggestion', 'all', 'all', 'all',
                NULL, NULL, 0, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """, (USAGE_RISK_SUBJECT, USAGE_RISK_BODY))
        template_id = cursor.lastrowid

    cursor.execute("""
        DELETE FROM comm_templates
        WHERE id <> ?
          AND (key = 'usage_risk_upgrade_suggestion'
               OR trigger_event = 'usage_risk_upgrade_suggestion')
          AND enabled = 0 AND subject = ? AND body = ?
    """, (template_id, USAGE_RISK_SUBJECT, USAGE_RISK_BODY))

    cursor.execute("""
        UPDATE comm_templates
        SET enabled = 0, updated_at = CURRENT_TIMESTAMP
        WHERE enabled = 1
          AND id NOT IN (
              SELECT MIN(id)
              FROM comm_templates
              WHERE enabled = 1
              GROUP BY trigger_event, trigger_provider,
                  COALESCE(subscription_scope, 'none'),
                  COALESCE(subscription_template_id, 0),
                  COALESCE(days_before, -999999),
                  COALESCE(days_after, -999999),
                  COALESCE(expiration_change_direction, 'all')
          )
    """)
    conn.commit()
