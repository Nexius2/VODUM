VODUM — Media Server Subscription & Access Manager (Beta)

VODUM is a self-hosted web application designed to manage users, libraries and subscriptions for media servers such as Plex (Jellyfin support in progress).

It acts as a central control panel to:

manage who has access to your servers,

control which libraries are shared,

track subscription status,

and automate follow-up emails and access restrictions.

⚠️ Beta: database structure and features may evolve. Regular backups are recommended.

🎯 What is VODUM for?

VODUM is built for Plex administrators who:

share their server with friends, family or paying users,

need a clear view of active / expired users,

want to automate access management and notifications,

and avoid manual tracking in spreadsheets or notes.

✨ Core Features
👤 User Management (Plex / Jellyfin)

Centralized list of all users

Plex users retrieved via the official API

Users can exist even without an active share

User status automatically derived from subscription state

🟡 Jellyfin support is currently in development

🗂️ Server & Library Management

Manage multiple media servers

Associate users with specific servers

Control which libraries are shared per user

Store advanced Plex sharing options:

sync permissions

camera upload

channel access

media filters (movies / TV / music)

Designed to reflect real Plex access, not just local metadata.

💳 Subscription Management

User-based subscription system

Start date / end date tracking

Automatic subscription status:

Active

Upcoming expiration

Expired

Subscription state drives access and notifications

✉️ Email Automation

Configurable email templates stored in database

Multiple email types:

upcoming expiration reminder

renewal reminder

subscription expired notice

Per-template delay configuration (number of days before/after expiration)

Daily automated mail processing

Planned:

Simple SMTP presets (Gmail, Outlook…)

Advanced OAuth authentication

🔒 Automated Access Control

Automatic restriction of library access for expired users

Access removal is done directly on Plex servers

No user deletion — access can be restored instantly

Multi-server aware logic

Designed to be safe, reversible and auditable.

🧱 Docker & Unraid Friendly

Fully containerized

Persistent /appdata structure

Automatic database initialization

One-time schema creation

Versioned migrations

Timestamped logs

🚀 Quick Start (Docker / Unraid)
Persistent storage

VODUM uses a single persistent directory:

/appdata
 ├── database.db
 ├── backups/
 └── logs/

Docker run
docker run -d \
  --name vodum \
  -p 5000:5000 \
  -v /mnt/user/appdata/vodum:/appdata \
  vodum/vodum:latest

⚙️ Configuration

No mandatory environment variables

All settings are managed through the web interface

Configuration is stored in the database

🛣️ Roadmap (excerpt)

Jellyfin full integration

Multi-language UI

OAuth mail providers

Role-based permission profiles

Public API

UI & UX improvements

🤝 Contributing

Contributions are welcome.

Please:

keep database migrations backward-safe

document schema changes

respect existing access logic

📄 License

MIT