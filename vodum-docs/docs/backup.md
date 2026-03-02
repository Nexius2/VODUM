---
title: Backup & Restore
---

<!-- =========================================================
VODUM Docs - Backup & Restore
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# 💾 Backup & Restore

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
Database • Backup • Restore • Retention
</span>

<br><br>

The **Backup & Restore** section allows you to manage **VODUM database backups**.

It provides:
- manual database backups
- automatic retention management
- backup restoration
- visibility on existing backup files

Backups are stored as **SQLite database files**.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 📦 Manual backup

The **Manual backup** panel lets you create a backup immediately.

### Create backup
Click **Create backup** to:
- generate a new SQLite backup file
- store it in the backup directory
- keep the current database state safely

> 💡 Manual backups are useful before:
> - major configuration changes  
> - upgrades  
> - maintenance operations  

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ⚙️ Backup settings (retention)

This section controls **automatic backup retention**.

### Retention duration
Defines how long backups are kept (in days).

Example:
- **30 days** → backups older than 30 days are automatically deleted

### Save settings
Click **Save settings** to apply the retention policy.

> 🧹 Cleanup is handled automatically by maintenance tasks.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ♻️ Restore a backup

The **Restore a backup** panel allows you to restore a previously created backup file.

### How it works
1. Select a `.sqlite` backup file
2. Click **Restore**
3. The current database is replaced by the selected backup

> ⚠️ **Warning**  
> Restoring a backup will **overwrite the current database**.  
> This action is irreversible.

### Recommended precautions
- create a manual backup before restoring
- ensure no critical tasks are running
- verify the backup file is correct

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📂 Available backups

The **Available backups** table lists all stored backup files.

### Columns explained

- **Name**: backup file name (timestamp-based)
- **Size**: file size
- **Modified**: last modification date
- **Restore**: allows restoring a selected backup

This view helps you:
- identify the most recent backup
- estimate database size
- select the correct restore point

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🔄 Automatic backups

Automatic backups are handled by **scheduled tasks**.

- backups are created at defined intervals
- old backups are cleaned according to retention settings

> 💡 Ensure backup-related tasks are enabled in the **Tasks** section.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Troubleshooting

### Backup not created
- verify disk permissions
- check available storage space
- inspect **Logs** for backup errors

---

### Restore fails
- ensure the file is a valid SQLite backup
- verify file permissions
- check **Logs** for restore-related errors

---

### Old backups not deleted
- verify retention settings
- ensure cleanup tasks are enabled
- inspect maintenance task logs

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- Backups contain **all VODUM configuration and data**.
- Store backup files securely.
- Regular backups are strongly recommended for production usage.

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Backup & Restore documentation
</span>
</div>
