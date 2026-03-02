---
title: 🏗 Architecture
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 🏗 Architecture

<span class="hint-badge">Flask • SQLite • Tasks engine • Providers</span>

<br><br>

</div>


## High-level components

VODUM is made of:

- **Web UI** (Flask templates)
- **Database** (SQLite by default; used for users, subscriptions, server config, templates, logs metadata)
- **Tasks engine** to run scheduled checks and apply access updates
- **Providers** layer for Plex/Jellyfin operations

---

## Data model (conceptual)

- Users
- Subscriptions (expiration dates)
- Servers (type + connectivity)
- Libraries (per server)
- Shared access rules (who can access what)
- Templates (mail/discord)
- Logs / history

!!! tip
    For a safe upgrade workflow, always export a backup before updating.

---

## Task orchestration

Tasks are responsible for:
- checking servers
- enforcing policies
- applying Plex/Jellyfin access updates
- dispatching notifications
- running backups/cleanup if enabled
