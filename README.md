# VODUM
### Media Server Subscription & Access Manager (Beta)

VODUM is a **self-hosted web application** designed to **centralize the management of users, libraries and subscriptions**
for media servers such as **Plex and Jellyfin**.

It provides a **single control panel** to handle access rights, subscriptions, notifications and automation,
without relying on external spreadsheets or manual reminders.

> ⚠️ **Beta notice**: the database schema and features may evolve. Regular backups are strongly recommended.

---

## 🎯 Purpose

VODUM is built for media server administrators who:

- share their server with friends, family or subscribers
- need a clear overview of **active, expiring and expired users**
- want to **automate access control** instead of managing shares manually
- want to **automate subscription-related email notifications**
- want a reliable alternative to manual tracking (notes, spreadsheets, reminders)

---

## ✨ Main Features

### 👤 User Management (Plex & Jellyfin)

- Centralized list of all users
- Plex and Jellyfin users retrieved via their respective APIs
- Users can exist in the database even without active library shares
- User status automatically derived from subscription state

Both **Plex and Jellyfin are fully supported**.

---

### 🗂️ Server & Library Management

- Manage **multiple media servers**
- Associate users with one or more servers
- Control which libraries are shared per user
- Store advanced Plex sharing options:
  - Sync permissions
  - Camera upload
  - Channel access
  - Media filters (Movies / TV / Music)

Designed to reflect **real server access configuration**, not just local metadata.

---

### 💳 Subscription Management

- Subscription system linked to users
- Start and end date tracking
- Automatic subscription states:
  - Active
  - Expiring soon
  - Expired
- Subscription state drives both **access control** and **notifications**

---

### ✉️ Email Automation

- Email templates stored directly in the database
- Multiple email types supported:
  - Upcoming expiration reminder
  - Renewal reminder
  - Subscription expired notification
- Per-template delay configuration
- Daily automated email processing

---

### 🔒 Automated Access Control

- Automatic restriction of library access for expired users
- Access removal performed **directly on Plex and Jellyfin servers**
- Users are never deleted
- Access can be restored instantly if a subscription is renewed
- Fully **multi-server aware** logic

---

### 🌍 Multi-language Interface

- Built-in multi-language support
- Language automatically detected from the browser
- Manual language selection available in settings
- Translation system based on JSON language files

---

### 🧱 Docker & Unraid Friendly

- Fully containerized
- Persistent `/appdata` directory
- Automatic database initialization
- One-time schema creation
- Versioned migrations
- Timestamped log files
- Until it becomes available through Community Applications (CA), the XML file can be found at the root of the GitHub repository.

---

## 🚀 Docker (Unraid)

> Until VODUM becomes available on **Community Applications (CA)**,
> you can install it manually on Unraid using the official template settings.

This method requires **no Docker knowledge** and uses **exactly the same configuration**
as the future CA template.

---

## ➕ Add VODUM to Unraid

1. Open the **Unraid Web UI**
2. Go to **Docker**
3. Click **Add Container**
4. Switch to **Advanced View**

---

## 🧩 Container configuration

Fill in the fields **exactly as shown below**.

### 🔹 Basic settings

**Name**
VODUM

**Repository**
nexius2/vodum:latest

**Network Type**
bridge

### 🔌 Port Mappings

| Container Port | Host Port | Description |
|---------------|----------|-------------|
| 5000 | 8097 | Web interface |

---

### 📁 Path Mappings

| Container Path | Host Path | Description |
|---------------|----------|-------------|
| /appdata | /mnt/user/appdata/vodum | Application data |
| /logs | /mnt/user/appdata/vodum/logs | Logs |
| /backups | /mnt/user/appdata/vodum/backups | Database backups |

---

### ⚙️ Environment Variables

| Variable | Value | Description |
|--------|------|-------------|
| TZ | Europe/Paris | Timezone |
| UID | 99 | User ID |
| GID | 100 | Group ID |
| DATABASE_PATH | /appdata/database.db | SQLite database location |

---

## ▶️ Start the container

5. Click **Apply**
6. Wait for the image to download and the container to start

---

## 🌐 Web Interface

Once the container is running, open VODUM at:
http://<unraid-ip>:8097
