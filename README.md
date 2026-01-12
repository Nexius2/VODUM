# VODUM
### Media Server Subscription & Access Manager (Beta)

VODUM is a **self-hosted web application** designed to manage **users, libraries and subscriptions**
for media servers such as **Plex** (*Jellyfin support in progress*).

It provides a **central control panel** to manage access, subscriptions and automation.

> ⚠️ Beta: database structure and features may evolve. Regular backups are recommended.

---

## 🎯 What is VODUM for?

VODUM is built for **Plex administrators** who:

- share their server with friends, family or paying users
- need a clear view of **active / expiring / expired users**
- want to **automate access management**
- want to **automate email notifications**
- want to avoid manual tracking (spreadsheets, notes, reminders)

---

## ✨ Core Features

### 👤 User Management (Plex / Jellyfin)

- Centralized list of all users
- Plex users retrieved via the official API
- Users can exist even without an active library share
- User status automatically derived from subscription state

> Jellyfin support is currently in development

---

### 🗂️ Server & Library Management

- Manage multiple media servers
- Associate users with specific servers
- Control which libraries are shared per user
- Store advanced Plex sharing options:
  - sync permissions
  - camera upload
  - channel access
  - media filters (movies / TV / music)

Designed to reflect **real Plex access**, not just local metadata.

---

### 💳 Subscription Management

- User-based subscription system
- Start and end date tracking
- Automatic subscription states:
  - Active
  - Expiring soon
  - Expired
- Subscription status drives access and notifications

---

### ✉️ Email Automation

- Configurable email templates stored in database
- Multiple email types:
  - upcoming expiration reminder
  - renewal reminder
  - subscription expired notice
- Per-template delay configuration
- Daily automated email processing

Planned:
- SMTP presets (Gmail, Outlook…)
- OAuth authentication

---

### 🔒 Automated Access Control

- Automatic restriction of library access for expired users
- Access removal performed directly on Plex servers
- Users are never deleted
- Access can be restored instantly
- Multi-server aware logic

---

### 🧱 Docker & Unraid Friendly

- Fully containerized
- Persistent `/appdata` directory
- Automatic database initialization
- One-time schema creation
- Versioned migrations
- Timestamped logs
- while in beta, run ./get-container.sh to install on unraid.

---

## 🚀 Quick Start (Docker / Unraid)

### Persistent storage

/appdata
├── database.db
├── backups/
└── logs/


### Docker

docker run -d \
  --name vodum \
  -p 5000:5000 \
  -v /mnt/user/appdata/vodum:/appdata \
  vodum/vodum:latest

### ⚙️ Configuration

- No mandatory environment variables
- All configuration is managed through the web interface
- Settings are stored in the database

---

### 🛣️ Roadmap (excerpt)

- Full Jellyfin integration
- Multi-language UI
- OAuth mail providers
- Role-based permission profiles
- Public API
- UI / UX improvements

---

### 📄 License

MIT
