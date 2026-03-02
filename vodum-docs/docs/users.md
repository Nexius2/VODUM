---
title: Users
---

<!-- =========================================================
VODUM Docs - Users
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# 👤 Users

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Users • Access • Subscriptions • Plex / Jellyfin
</span>

<br><br>

The **Users** page is used to manage **Plex and Jellyfin users** and their access
to servers and libraries through **subscriptions**.

It provides a **centralized view** of:
- who has access
- until when
- on which servers
- and to how many libraries

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 🔍 Search & filters

At the top of the page, you can quickly filter the user list.

### 🔎 Search
The **Search** field allows you to search by:
- username
- email address

The search is applied in real time.

---

### 🏷️ Status filter

The **Status** dropdown lets you filter users by their current state, such as:
- Active
- Expiring soon
- Expired
- Other internal states depending on your configuration

> 💡 Tip  
> Combining **Search** and **Status** is the fastest way to find a specific user.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📋 Users table

The main table displays all users known by VODUM.

Each row represents **one user** and summarizes their current access.

---

### 🧱 Columns explained

#### 👤 Name
The username as known by:
- Plex
- Jellyfin
- or manually created in VODUM

This is the **primary identifier** used throughout the interface.

---

#### 📧 Email
The email address associated with the user.

- If the email is not available from the API, it will be displayed as  
  **“Not available”**
- Email is mainly used for:
  - subscription reminders
  - expiration notifications

> ⚠️ If no email is available, mailing features will not apply to this user.

---

#### 🟢 Status
Displays the current subscription status of the user.

Typical values:
- **Active**: subscription is valid
- **Expiring soon**: subscription is close to expiration
- **Expired**: subscription is no longer valid

Status is calculated automatically based on the **subscription expiration date**
and your configured delays.

---

#### 📅 Expiration
The **expiration date** of the user’s subscription.

This date is the **single source of truth** for:
- reminders
- access updates
- automatic deactivation

> 💡 When this date is reached or passed, automated tasks may remove access depending on your configuration.

---

#### 🖥️ Servers
Number of servers (Plex and/or Jellyfin) the user currently has access to.

This value is computed from:
- active subscriptions
- shared servers

---

#### 📚 Libraries
Total number of libraries the user has access to across all servers.

This includes:
- movie libraries
- TV show libraries
- other media types depending on the server configuration

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🔄 How access is managed

<span style="display:inline-block;padding:10px 12px;border-radius:12px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;">
<b>Important concept</b><br>
Users do not receive access directly.<br>
Access is granted through <b>subscriptions</b> and applied by automated tasks.
</span>

The Users page:
- **does not directly modify server access**
- reflects the **current state** of subscriptions and access rules

Actual access updates happen when:
- scheduled tasks run
- or when a manual sync/update task is executed

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ✅ Typical usage

1. Open the **Users** page
2. Search or filter for a user
3. Check:
   - status
   - expiration date
   - number of servers and libraries
4. If something looks incorrect:
   - check the user’s **subscription**
   - check **Tasks** execution
   - inspect **Logs**

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Troubleshooting

### User shown as Active but has no access
- verify the subscription is linked correctly
- ensure access update tasks have run
- check **Logs** for access update errors

### User expired but still has access
- check if the access removal task is enabled
- verify task scheduling
- inspect **Logs** for warnings or skipped jobs

### Email shows “Not available”
- the user may not expose an email via the API
- mailing features will not apply to this user

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- The Users page is a **read and monitoring interface**.
- All modifications are driven by:
  - subscriptions
  - server/library configuration
  - automated tasks
- Manual changes should be avoided directly on servers to keep consistency.

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Users documentation
</span>
</div>
