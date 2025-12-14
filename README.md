VODUM — Media Server Subscription Manager (Beta)

VODUM is a self-hosted tool to manage Plex users (Jellyfin coming soon), track subscriptions, control library access, and automate notifications — designed with Docker and Unraid in mind.

⚠️ Beta: features and database schema may evolve. Backups are recommended.

✨ Highlights

🎬 User management: users, servers, libraries, access rights — all centralized

📆 Subscription lifecycle: expiration tracking, status automation (active, reminder, expired…)

✉️ Email notifications: customizable templates, pre-expiry reminders & post-expiry actions

🧱 Unraid-friendly: persistent appdata, clean startup, auto DB init, migrations, logs

🚀 Quick Start (Docker / Unraid)
Persistent storage

VODUM uses a single persistent root directory (recommended on Unraid):

/appdata
 ├── database.db
 ├── backups/
 └── logs/


✅ Make sure /appdata is mapped to a persistent volume.

Docker run

Replace the image name with your actual published image.

docker run -d \
  --name vodum \
  -p 5000:5000 \
  -v /mnt/user/appdata/vodum:/appdata \
  vodum/vodum:latest

⚙️ Configuration

No mandatory environment variables for now.

All configuration is stored in the database and editable via the UI.

🧩 Unraid notes

VODUM is designed to behave nicely on Unraid:

Persistent /appdata

Clean startup logic

Automatic DB initialization

Automatic V1 → V2 migration

Logs visible via docker logs

📦 An Unraid Community Apps template is planned.

🔐 Security

No credentials are hardcoded

Sensitive data is stored only locally in the database

Intended for private / self-hosted deployments

🛣️ Roadmap (non-exhaustive)

Jellyfin integration

Multi-language UI

OAuth-based email providers (Gmail, Outlook…)

Advanced permission profiles

API endpoints

UI improvements

🤝 Contributing

Contributions are welcome.

Please:

keep migrations backward-safe

respect the database architecture

document any schema changes

📄 License

MIT