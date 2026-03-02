---
title: Subscriptions
---

<!-- =========================================================
VODUM Docs - Subscriptions
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# 🎟️ Subscriptions

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Users • Duration • Expiration • Access
</span>

<br><br>

The **Subscriptions** page is used to **grant, extend, or adjust subscription
time** for users.

A subscription defines **until when** a user should have access.
Actual access is then **applied automatically** to Plex and Jellyfin servers
by background tasks.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 🎯 Target users

This section defines **which users will receive the subscription update**.

Two modes are available:

---

### 👥 All users

<span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Global selection
</span>

- Includes **all users across all servers**
- Useful for:
  - global gifts
  - compensation
  - incident recovery
  - mass extension

---

### 🖥️ Users from a server

<span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Server-scoped selection
</span>

- Includes **only users linked to a specific server**
- Useful when:
  - one server was down
  - one server needs compensation
  - access changes are server-specific

> 💡 The selected mode directly impacts **how many users** will be affected.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ⏳ Gift duration

This section defines **how much time will be added** to the subscription.

Predefined durations are available for quick actions:

- **1 day**
- **7 days**
- **1 month**
- **3 months**
- **6 months**
- **12 months**

The selected duration is added to the user’s **current expiration date**.

> 📅 If a user already has an active subscription, the duration extends it.  
> 📅 If a user is expired, the subscription is renewed from the current date.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📝 Options (comment)

The **Options** field allows you to add a **free-text note**, such as:
- compensation
- gift
- incident
- manual adjustment

This field is informational but useful for:
- tracking why a subscription was modified
- auditing changes later

---

### 🔁 Reminder reset behavior

If the **new expiration date** is **later than the previous one**:
- reminder flags
- warning states

will be **reset automatically**.

This ensures:
- reminders are sent again at the correct time
- users do not miss notifications after an extension

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🎁 Gift subscription

Clicking **Gift subscription** will:

1. Calculate the new expiration date
2. Update subscription data in VODUM
3. Reset reminders if applicable
4. Mark users for access update

⚠️ **Important**  
This action **does not immediately modify server access**.

Actual access changes are applied when:
- scheduled tasks run
- or a manual access update task is executed

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🔄 How subscriptions affect access

<span style="display:inline-block;padding:10px 12px;border-radius:12px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;">
<b>Core concept</b><br>
Subscriptions define <b>time</b>, not direct access.<br>
Access is applied later by automated tasks.
</span>

- Subscriptions define **validity period**
- Servers & libraries define **what can be accessed**
- Tasks synchronize subscriptions with Plex/Jellyfin

This design ensures:
- consistency
- automation
- reproducible access states

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ✅ Typical use cases

### 🎁 Gift or compensation
- Select **All users**
- Choose a duration (e.g. 7 days)
- Add an optional comment
- Apply the gift

---

### 🖥️ Server outage compensation
- Select **Users from a server**
- Choose the affected server
- Select an appropriate duration
- Apply the subscription

---

### 🔄 Manual extension
- Use the page to extend one or more users
- Let automated tasks handle access updates

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Troubleshooting

### Subscription updated but access not changed
- ensure access update tasks are enabled
- check **Tasks** status
- inspect **Logs** for skipped or failed updates

### Reminders not sent again
- verify that the new expiration date is later than the previous one
- check **Mailing** configuration
- inspect reminder-related logs

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- Subscriptions are **time-based**, not access-based.
- Avoid manual changes directly on Plex/Jellyfin.
- VODUM should remain the **single source of truth** for expiration management.

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Subscriptions documentation
</span>
</div>
