---
title: Dashboard
---

<!-- =========================================================
VODUM Docs - Dashboard
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# 📊 Dashboard

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Overview • Users • Servers • Tasks • Latest logs
</span>

<br><br>

The **Dashboard** is the home page of VODUM.  
It provides an **instant global overview** of your system:

- **Users** status (active, expiring, reminders, expired)
- **Servers** status (Plex / Jellyfin, online/offline)
- **Automated tasks** health
- **Latest logs** for quick diagnostics

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 🎛️ Summary cards (top section)

At the top of the Dashboard, summary cards display the most important information at a glance.

---

### 👤 Users

<span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Purpose: instantly check subscription health
</span>

This card shows:
- **Active users**: users with an active subscription
- **Expiring soon**: users whose subscription will expire soon
- **Reminder**: users scheduled for a reminder email
- **Expired**: users with an expired subscription
- **Total**: total number of users known by VODUM

> 💡 Tip  
> If **Expiring soon** or **Expired** increases, check the **Subscriptions** and **Tasks** sections to ensure everything is configured and running properly.

---

### 🖥️ Servers (Plex / Jellyfin)

<span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Purpose: monitor server availability
</span>

This card displays:
- total number of **Plex** and **Jellyfin** servers
- number of **Online** and **Offline** servers

> ✅ **Online** means VODUM can reach the server (API / health check).  
> ❌ **Offline** means the server did not respond during the last check.

---

### ⏱️ Tasks

<span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Purpose: ensure automation is running
</span>

This card shows:
- **Active tasks**: enabled or scheduled tasks
- **In error**: tasks that failed during their last execution

> ⚠️ If you see tasks in error, check the **Latest logs** section or open the **Logs** page for details.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧾 Servers list

This section displays a detailed list of all configured servers:

- **Server name**
- **Type**: Plex or Jellyfin (badge)
- **URL**
- **Status**: Online / Offline
- **Last check**: timestamp of the last health check

### ✅ What this section is useful for
- quickly detecting an unreachable server
- validating server URLs
- ensuring monitoring tasks are running correctly

> 🔎 If **Last check** never updates  
> Verify that scheduled tasks are running and inspect the **Logs** for errors.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧱 Latest logs

The **Latest logs** panel displays the most recent system events.

Typical entries include:
- task start and completion
- success or error messages
- processing information (e.g. *No job to process*)
- next scheduled execution time

<span style="display:inline-block;padding:10px 12px;border-radius:12px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;">
<b>Why this matters</b><br>
This is the first place to look when something does not behave as expected.
</span>

### 🔗 “View all”
The **View all** link opens the full **Logs** page, where the complete log history is available.

> 💡 Recommendation  
> Use **Latest logs** for quick checks and the **Logs** page for deeper investigation.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ✅ Recommended workflow

1. Open the Dashboard
2. In a few seconds, check:
   - Users (expiring / expired)
   - Servers (online / offline)
   - Tasks (errors)
3. If an issue appears:
   - check **Latest logs**
   - open **Logs** for details
   - adjust configuration in **Tasks**, **Settings**, or related sections

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Quick troubleshooting

### Server shown as Offline
- verify the server URL
- ensure the server is reachable from the VODUM host
- check **Latest logs** for network or authentication errors

### Tasks in error
- open the **Logs** page
- identify the failing task
- verify related configuration (tokens, SMTP, API access, etc.)

### Expiring / expired users not handled
- verify that automated tasks are enabled
- check **Mailing** configuration and delays
- confirm that access update or reminder tasks are running

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- The Dashboard is a **monitoring view**: it shows status but does not manage data directly.
- All values depend on:
  - synchronizations
  - automated tasks
  - changes made in Users, Subscriptions, or Servers

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Dashboard documentation
</span>
</div>
