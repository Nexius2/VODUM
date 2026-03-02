---
title: 🚀 Getting Started
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 🚀 Getting Started

<span class="hint-badge">Installation • First run • Admin setup • Security • Updates</span>

<br><br>

</div>


## ✅ Prerequisites

- A machine capable of running Docker (Unraid, Linux, Windows + Docker Desktop, etc.)
- Access to your Plex/Jellyfin servers (URL + token/API key)
- (Optional) An SMTP account for email notifications
- (Optional) A Discord bot token for Discord notifications

!!! tip "Unraid users"
    Map the VODUM **/app/data** volume to a persistent location on your array/cache.

---

## 🐳 Docker Installation (recommended)

Example (generic Docker):

```bash
docker run -d   --name vodum   -p 5000:5000   -v /path/to/vodum-data:/app/data   -e VODUM_SECRET_KEY="change_me"   -e VODUM_ALLOWED_NETS="127.0.0.1/32,192.168.0.0/16"   nexius2/vodum:latest
```

### Key volumes

- `/app/data` contains:
  - the database
  - backups (if enabled)
  - local app state

---

## 🔐 First run: create the admin account

On first access, VODUM will guide you through **admin setup** (username/password).

!!! warning
    Keep your admin password safe. If you use the recovery/reset feature, make sure it’s restricted to trusted access only.

---

## 🌐 Network protection (IP filter)

VODUM can restrict access to allowed networks.

- `VODUM_IP_FILTER`  
  - `1` (default): enabled  
  - `0`: disabled
- `VODUM_ALLOWED_NETS`  
  A comma-separated list of CIDRs, e.g.:
  `127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`

!!! tip
    Put VODUM behind a reverse proxy (Traefik / Nginx Proxy Manager / Caddy) and enable HTTPS.

---

## 🧭 Typical onboarding workflow

1. **Add your servers** → [Servers](servers.md)
2. **Sync libraries** → [Libraries](libraries.md)
3. **Import / manage users** → [Users](users.md)
4. **Set subscription expirations** → [Subscriptions](subscriptions.md)
5. **Define policies** → [Policies](policies.md)
6. **Enable tasks** → [Tasks](tasks.md)
7. (Optional) Configure **Mailing** and/or **Discord**

---

## 🔄 Updates & migrations

VODUM includes an update-check mechanism and migrations.

- Always backup your database before major updates → [Backup](backup.md)
- Check the logs if something looks off after an upgrade → [Logs](logs.md)

!!! important
    If you run VODUM on Unraid Community Apps, updates are usually managed by Unraid. Still, **back up before updating**.
