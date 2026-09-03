from __future__ import annotations


LEGACY_PAYMENT_API_TABLES = (
    "payment_webhook_events",
    "payment_transactions",
    "payment_orders",
    "payment_provider_configs",
)


def _retire_empty_legacy_api_tables(cursor, table_exists) -> None:
    """Drop the prototype group only when every existing table is empty."""
    existing = [
        table for table in LEGACY_PAYMENT_API_TABLES if table_exists(cursor, table)
    ]
    if any(
        int(cursor.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0)
        for table in existing
    ):
        return
    for table in existing:
        cursor.execute(f'DROP TABLE "{table}"')


def ensure_payment_schema(conn, cursor, *, table_exists, ensure_column) -> None:
    """Create external renewal links; legacy API tables are left inert if present."""
    ensure_column(cursor, "settings", "portal_payment_links_enabled", "INTEGER NOT NULL DEFAULT 0")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_payment_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            description TEXT,
            url TEXT NOT NULL,
            button_label TEXT,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
            sort_order INTEGER NOT NULL DEFAULT 0,
            subscription_template_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(subscription_template_id) REFERENCES subscription_templates(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_portal_payment_links_active ON portal_payment_links(enabled,sort_order,id)")
    ensure_column(cursor, "portal_payment_links", "method_type", "TEXT NOT NULL DEFAULT 'custom'")
    ensure_column(cursor, "portal_payment_links", "details_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(cursor, "portal_payment_links", "reference_template", "TEXT")
    ensure_column(cursor, "portal_payment_links", "show_amount", "INTEGER NOT NULL DEFAULT 1")
    _retire_empty_legacy_api_tables(cursor, table_exists)
    conn.commit()
