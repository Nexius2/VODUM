# Backup & import

## Quick start

1. Open **Backup** and create a **full backup** (ZIP).
2. Download it and keep it somewhere safe: it contains your encryption key.
3. Check that automatic backups are enabled in [Tasks](tasks.md).

## Backup types

- **Full ZIP**: database, attachments and encryption key. It is enough on its
  own to restore VODUM, and it is very sensitive: keep it private.
- **Database only (SQLite)**: just the database. You also need to keep the
  `vodum.encryption_key` file, otherwise saved passwords and tokens cannot be read.

Automatic backups and their cleanup follow the age and number limits you set.
The page also shows the database integrity check.

Portal accounts, sessions and their history are in the database, so every full
backup contains them.

## Restore

Choose an existing backup, or upload a `.zip`, `.db` or `.sqlite` file. VODUM
checks the file, waits for running tasks to finish, replaces the data, then
stops so that the container restarts. Tasks stay paused until the restart.

After a restore:

- the data is back to the date of the backup (subscriptions, portal, collections…);
- media requests that were pending in the backup are closed, so that a title is
  not added twice: check Sonarr/Radarr before requesting it again;
- if the encryption key is set in the environment, it must match the one in
  the backup.

Never restore an archive from an untrusted source.

!!! note "Personal data"
    If you erased a user's personal data, older backups may still contain it
    until they are deleted. If you restore such a backup, erase that data again.

## Tautulli import

Upload a Tautulli database, choose the destination Plex server and what to do
with unknown users and libraries. The import runs in the background and its
temporary files are cleaned up afterwards.

??? info "Technical details"
    The command-line import supports `--summary-only` to print a single JSON result.
