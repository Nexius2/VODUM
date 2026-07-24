def ensure_welcome_template_schema(conn, cursor, *, table_exists) -> None:
    if table_exists(cursor, "welcome_email_templates"):
        return

    print("Creating table: welcome_email_templates")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS welcome_email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL CHECK (provider IN ('plex','jellyfin')),
            server_id INTEGER NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider, server_id),
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()


def seed_welcome_templates(conn, cursor) -> None:
    templates = {
        "plex": (
            "Welcome to Plex - {server_name}",
            """Hi {firstname} {lastname},

    You've been invited to access our Plex server.

    1) Create (or sign in to) your Plex account using this email: {email}
    2) Accept the invitation from Plex
    3) Open the server and start watching

    Server name: {server_name}

    Need help?
    - Install Plex on your device (TV / mobile / web)
    - Sign in with your Plex account
    - Accept the share invitation
    - You will then see the server in your Plex home

    Regards,
    {brand_name}
    """,
        ),
        "jellyfin": (
            "Welcome to Jellyfin - {server_name}",
            """Hi {firstname} {lastname},

    Your Jellyfin account is ready.

    Server: {server_name}
    URL: {server_url}
    Username: {login_username}
    Temporary password: {temporary_password}

    How to log in:
    - Open the URL above (web)
    - Or install the Jellyfin app (Android / iOS / TV)
    - Sign in with your username and password

    Regards,
    {brand_name}
    """,
        ),
    }
    for provider, (subject, body) in templates.items():
        cursor.execute(
            "SELECT 1 FROM welcome_email_templates WHERE provider=? AND server_id IS NULL",
            (provider,),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO welcome_email_templates(provider, server_id, subject, body)
                VALUES (?, NULL, ?, ?)
                """,
                (provider, subject, body),
            )
            print(f"Default welcome template inserted: {provider} / server_id=None")
    conn.commit()
