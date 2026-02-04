# VODUM
### Media Server Subscription, Access & Policy Manager (Beta)

VODUM is a **self-hosted web application** designed to **centralize and automate the management of users, subscriptions and access rights**
for media servers such as **Plex and Jellyfin**.

Its primary purpose is to act as a **subscription service layer** on top of media servers, handling users, access rules,
monitoring and communication in a single interface.

VODUM replaces manual workflows (spreadsheets, notes, reminders, manual sharing)
with an **automated, policy-driven system**.

> ⚠️ **Beta notice**: the database schema and features may evolve. Regular backups are strongly recommended.

---

## 🎯 Purpose

VODUM is built for media server administrators who:

- share their Plex or Jellyfin servers with friends, family or subscribers
- need a clear overview of **active, expiring and expired users**
- want to manage access like a **real subscription service**
- want to **automate access control** instead of editing shares manually
- want users to be **notified automatically** about their subscription status

VODUM acts as a **subscription-aware management layer** on top of Plex and Jellyfin.

---

## ✨ Main Features

### 👤 User Management (Plex & Jellyfin)

VODUM maintains a **central database of all users**, independently from their current access state.

- Users retrieved via Plex and Jellyfin APIs
- Users can exist without active library shares
- A single user can be linked to multiple servers
- User state automatically derived from subscription status

VODUM becomes the **single source of truth** for user management.

---

### 🗂️ Server & Library Management

- Manage multiple Plex and Jellyfin servers
- Associate users with one or more servers
- Control exactly which libraries are accessible per user
- Store advanced Plex sharing options:
  - Sync permissions
  - Camera upload
  - Channel access
  - Media filters (Movies / TV / Music)

VODUM mirrors **real server access**, not just theoretical permissions.

---

### 💳 Subscription Management (Core Feature)

Subscriptions are the **heart of VODUM**.

Each subscription includes:

- Start date
- End date
- Automatic state calculation:
  - Active
  - Expiring soon
  - Expired

The subscription state directly drives:

- Library access
- Policy enforcement
- Email notifications

VODUM behaves like a **real subscription service**, not a simple reminder tool.

---

### ✉️ User Mailing & Notifications

VODUM includes a **built-in mailing system** to communicate automatically with users.

- Email templates stored in the database
- Multiple email types:
  - Upcoming expiration reminder
  - Renewal reminder
  - Subscription expired notification
- Per-template delay configuration
- Daily automated email processing

This removes the need to manually track and warn users.

---

### 🔒 Automated Access Control

- Automatic access restriction for expired users
- Applied **directly on Plex and Jellyfin servers**
- Users are never deleted
- Access is restored instantly upon renewal
- Fully multi-server aware logic

VODUM never relies on local flags only: **changes are applied on the servers themselves**.

---

### 📊 Monitoring & Policies

VODUM continuously monitors server activity and user behavior.

- Track active sessions in real time
- Monitor IP usage and concurrent streams
- Detect abnormal situations automatically
- Enforce policies:
  - warnings
  - session termination
  - access restrictions

Policies make VODUM an **active regulation system**, not just a passive dashboard.

---

### 🌍 Multi-language Interface

- Browser language auto-detection
- Manual language selection available in settings
- Translation system based on JSON language files

---

### 🧱 Docker & Unraid Friendly

- Fully containerized application
- Designed for Unraid and standard Docker hosts
- Persistent `/appdata` directory
- Automatic database initialization
- One-time schema creation
- Versioned migrations
- Timestamped log files

---

## 🚀 Installation (Docker / Unraid)

VODUM is distributed as a Docker image and is **fully compatible with Unraid**.

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
