---
title: 💬 Discord
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 💬 Discord

<span class="hint-badge">Bot token • Templates • Campaigns • History</span>

<br><br>

</div>


VODUM can send notifications to Discord using a bot.

---

## ✅ What Discord integration is used for

- Summary reports
- Subscription warnings (optional)
- Campaign notifications
- Administrative alerts

---

## ⚙️ Setup

1. Create a Discord bot
2. Invite it to your server
3. Copy the **bot token**
4. Paste it in VODUM Settings (Discord section)

!!! warning
    Keep your bot token secret. If leaked, reset it in Discord Developer Portal.

---

## 🧩 Modules

### Templates
Create reusable messages (variables can be injected depending on context).

### Campaigns
Send structured messages to a target channel.

### History
Audit what was sent and when.

---

## Troubleshooting

- Bot is not ready / not connected:
  - verify token
  - verify container has outbound internet
  - check logs for Discord validation errors
