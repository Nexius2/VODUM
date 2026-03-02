---
title: Tasks
---

<!-- =========================================================
VODUM Docs - Tasks
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# ⏱️ Tasks

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Automation • Scheduler • Background jobs
</span>

<br><br>

The **Tasks** page lists all **automated jobs** executed by VODUM.

Tasks are responsible for:
- synchronizing Plex and Jellyfin data
- applying access changes
- sending emails
- maintaining the database
- running periodic maintenance operations

This page is the **control center** of VODUM’s automation.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 📋 Tasks table overview

Each row represents **one scheduled task**.

The table provides full visibility on:
- what the task does
- when it runs
- its current state
- its last and next execution time

---

## 🧱 Columns explained

### 🆔 ID
Internal identifier of the task.

Used mainly for:
- logs
- debugging
- internal references

---

### 🏷️ Name
Human-readable task name.

This describes **what the task does** at a high level.

---

### 📝 Description
More detailed explanation of the task purpose.

Some descriptions may reference internal identifiers used by the system.

---

### 🗓️ Schedule
Defines **how often** the task runs.

Examples:
- Every 2 minutes
- Every hour
- Every day at 03:30
- Every 6 hours

Schedules are defined internally and cannot be edited from the UI.

---

### 🟢 Status
Current state of the task.

Possible values:
- **idle**: task is enabled and waiting for its next execution
- **disabled**: task is turned off and will not run automatically

> ⚠️ Disabled tasks do not run, even if conditions are met.

---

### 🕒 Last run
Timestamp of the last execution of the task.

A dash (`-`) means the task has not run yet.

---

### ⏭️ Next run
Timestamp of the next scheduled execution.

If the task is disabled, this value is empty.

---

### ▶️ Actions
Allows manual interaction with the task.

- **Run now**: triggers the task immediately
- Disabled tasks cannot be run manually

> 💡 Manual runs are useful for testing or forcing synchronization.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ⚙️ Task categories

### 🔄 Synchronization tasks

These tasks keep VODUM in sync with Plex and Jellyfin.

Examples:
- **Plex synchronization**  
  Synchronizes Plex users, servers and libraries.
- **Jellyfin synchronization**  
  Synchronizes Jellyfin users, servers and libraries.

They ensure that:
- users exist in VODUM
- servers and libraries are up to date

---

### 🔐 Access update tasks

These tasks apply **pending access changes** to media servers.

Examples:
- **Apply Plex access updates**
- **Apply Jellyfin access updates**

They process:
- subscription changes
- expired users
- library access updates

> 💡 These tasks usually run frequently (every few minutes).

---

### 📧 Mailing tasks

Responsible for sending emails:
- pre-expiration warnings
- reminders
- expired account notifications
- campaign emails

Examples:
- **Send expiration emails**
- **Send campaign emails**

> ⚠️ These tasks depend on correct **Mailing** configuration.

---

### 🧹 Maintenance tasks

Used for housekeeping and maintenance.

Examples:
- **Automatic backup**
- **Automatic cleanup of backups**
- **Cleanup users without libraries**
- **Checks server availability and updates their real name**
- **Automatic user status update**

These tasks keep the system clean, consistent, and performant.

---

### 🚫 Disable expired users

This task removes access for users whose subscriptions have expired.

- Access is removed from Plex/Jellyfin
- Users are not deleted
- Access can be restored if the subscription is renewed

> ⚠️ If this task is disabled, expired users may keep access longer than expected.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ▶️ Manual execution (Run now)

Clicking **Run now** will:
- execute the task immediately
- generate logs
- update the Last run timestamp

Manual execution:
- does not change the schedule
- is safe to use for diagnostics

> 💡 Recommended after configuration changes.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🔄 How tasks fit into VODUM

<span style="display:inline-block;padding:10px 12px;border-radius:12px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;">
<b>Key concept</b><br>
VODUM relies on tasks for all critical operations.<br>
Without tasks, data will not stay in sync.
</span>

- Users define *who*
- Subscriptions define *until when*
- Servers & libraries define *what*
- Tasks apply everything automatically

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Troubleshooting

### Task does not run
- verify the task is **not disabled**
- check **Next run**
- inspect **Logs** for scheduler errors

---

### Task runs but does nothing
- this may be normal (e.g. “no job to process”)
- check logs to confirm behavior

---

### Access not updated
- ensure access update tasks are enabled
- check subscription status
- inspect logs for skipped updates

---

### Emails not sent
- verify SMTP or OAuth configuration
- ensure mailing tasks are enabled
- inspect mailing logs

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- Tasks are designed to be **idempotent** (safe to run multiple times).
- Disabling tasks may lead to inconsistencies.
- For production use, all critical tasks should remain enabled.

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Tasks documentation
</span>
</div>
