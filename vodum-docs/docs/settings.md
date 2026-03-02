---
title: Settings
---

<!-- =========================================================
VODUM Docs - Settings
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# ⚙️ Settings

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Configuration • Behavior • System
</span>

<br><br>

The **Settings** page controls the **global behavior of the VODUM application**.

These settings affect:
- language and timezone
- subscription defaults
- expiration warnings
- system behavior
- task execution

Changes made here impact **all users, subscriptions, and automated tasks**.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 🌐 General settings

This section defines the global application preferences.

### Language
Select the interface language.

- **Auto**: uses the browser language
- Other languages may be available depending on configuration

> 💡 Language selection only affects the UI, not stored data.

---

### Timezone
Defines the timezone used by VODUM.

This affects:
- task scheduling
- expiration dates
- logs timestamps
- mailing schedules

> ⚠️ Ensure this matches your server timezone to avoid inconsistencies.

---

### Admin email
The administrator email address.

Used for:
- internal notifications
- default sender or contact reference
- future administrative features

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📆 Subscription settings

Controls default behaviors for subscriptions.

### Default subscription duration (days)
Defines the default number of days for a new subscription.

Example:
- **90 days** → new subscriptions last 90 days by default

---

### Delete user X days after expiration
Defines how long expired users are kept before deletion.

- Value in days
- Deletion is handled by automated tasks

> ⚠️ Deletion is irreversible.  
> Access removal usually happens before deletion.

---

### Disable user on expiration
When enabled:
- users are automatically disabled as soon as their subscription expires
- access is removed by access update tasks

When disabled:
- users may keep access until cleanup tasks run

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ⏳ Status warning delays

This section controls **pre-expiration warnings and reminders**.

### Days before expiration (pre-notice)
Defines how many days before expiration the **first warning** is triggered.

Typical use:
- early notification
- preparation for renewal

---

### Days before expiration (reminder)
Defines how many days before expiration the **final reminder** is sent.

Usually closer to the expiration date.

> 💡 These values are used by mailing and status update tasks.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🖥️ System settings

Controls global system behavior.

### Enable scheduled tasks
When enabled:
- background tasks are executed automatically
- synchronization, mailing, cleanup and updates occur normally

When disabled:
- **no automated task will run**
- manual execution is still possible

> ⚠️ Disabling this will freeze most automation features.

---

### Maintenance mode
When enabled:
- application enters maintenance state
- intended for updates or critical operations

Typical use cases:
- database maintenance
- upgrades
- migrations

---

### Debug mode
When enabled:
- additional logs are generated
- more detailed error messages may appear

> ⚠️ Debug mode should be disabled in production unless troubleshooting.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 💾 Saving settings

Click **Save** to apply changes.

- Changes are stored immediately
- Some changes may require task execution to fully apply
- Logs will reflect configuration updates

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🔄 How settings affect VODUM

<span style="display:inline-block;padding:10px 12px;border-radius:12px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;">
<b>Important concept</b><br>
Settings define the global rules.<br>
Tasks apply those rules automatically.
</span>

- Subscriptions use default durations
- Mailing uses warning delays
- Tasks rely on timezone and scheduling
- Cleanup and disable behavior depends on these values

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Troubleshooting

### Tasks not running
- ensure **Enable scheduled tasks** is checked
- verify maintenance mode is disabled

---

### Emails sent at wrong time
- check timezone
- verify warning delays

---

### Users not disabled or deleted
- check subscription settings
- ensure relevant tasks are enabled
- inspect **Logs**

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- Settings apply globally.
- Incorrect values can affect automation.
- Always review settings after upgrades or migrations.

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Settings documentation
</span>
</div>
