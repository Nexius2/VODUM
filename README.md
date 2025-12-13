VODUM –  Media server Subscription Manager (BETA)

VODUM is a self-hosted management tool designed to monitor Plex & jellyfin (on it's way) users, manage subscriptions, control library access, and automate notifications.


✨ Key Features

🎬 user management

Track users, servers, libraries, and access rights

Centralized view of all media servers

📆 Subscription lifecycle

Expiration tracking

Status automation (active, reminder, expired…)

✉️ Email notifications

Customizable templates

Pre-expiry reminders & post-expiry actions

🚀 Quick Start (Docker / Unraid)
Persistent directories

VODUM uses the following persistent paths:

/appdata
 ├── database.db
 ├── backups/
 └── logs/


Make sure /appdata is mapped to a persistent volume in Docker / Unraid.

Environment

No mandatory environment variables for now.
All configuration is stored in the database and editable via the UI.

🐳 Docker Image

(Replace with your actual image name once published)

docker run -d \
  --name vodum \
  -p 5000:5000 \
  -v /mnt/user/appdata/vodum:/appdata \
  vodum/vodum:latest

🧩 Unraid Support

VODUM is designed to be Unraid-friendly:

Persistent /appdata

Clean startup logic

Automatic DB initialization

Automatic V1 → V2 migration

Logs visible via Docker logs

An Unraid Community App template is planned.



🔐 Security Notes

No credentials are hardcoded

Sensitive data is stored only in the local database

Designed for private / self-hosted environments

🛣️ Roadmap (Non-exhaustive)

Jellyfin integration

Multi-language UI

OAuth-based email providers

Advanced permission profiles

API endpoints

UI improvements

🤝 Contributing

Contributions are welcome!

Please:

keep migrations backward-safe

respect the database architecture

document any schema changes

📄 License

MIT

