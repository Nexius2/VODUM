---
title: 🖥 Servers
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 🖥 Servers

<span class="hint-badge">Plex • Jellyfin • Connectivity • Health checks</span>

<br><br>

</div>


The **Servers** module is where you connect VODUM to your Plex/Jellyfin instances.

---

## ➕ Add a server

You can register multiple servers.

Typical fields:

- **Server type**: Plex or Jellyfin
- **Name**: friendly name for the UI
- **Base URL**: e.g. `http://192.168.1.10:32400` (Plex)
- **Token / API key**: used to query libraries and apply access

!!! warning
    Keep tokens private. Prefer using the built-in “eye” toggle when available, and never share screenshots with tokens visible.

---

## ✅ Health checks

VODUM can periodically check server availability.

You’ll see:
- server online/offline status
- last check timestamps
- potential connectivity errors

---

## 🔁 Sync strategy

After adding a server, you usually need to:

1. Fetch libraries → [Libraries](libraries.md)
2. Sync users access
3. Enable tasks for periodic checks → [Tasks](tasks.md)

---

## 🧯 Troubleshooting

If a server is “offline” but reachable:

- Verify the URL is reachable from the VODUM container (DNS / routing / firewall)
- Verify token validity
- Check logs for the detailed error → [Logs](logs.md)
