# Backup & Import

## Backup types

- **Full ZIP** — SQLite database, attachments and encryption key. Self-contained
  and highly sensitive.
- **Raw DB/SQLite** — database only. Preserve `vodum.encryption_key` separately.

Automatic backup and cleanup tasks enforce configured age and file-count
retention. Database integrity diagnostics are visible on the page.

## Restore

Select an existing backup or upload `.zip`, `.db` or `.sqlite`. VODUM validates
SQLite integrity, required tables, ZIP paths, member count and extracted size.
Restore enters maintenance mode, replaces data safely and exits the process so
the container can restart.

When an encryption key is supplied through the environment, it must match the
key contained in a full backup. Never restore an untrusted archive.

## Tautulli import

Upload a Tautulli SQLite database, select the destination Plex server and choose
how unknown users/libraries are handled. Imports are queued, deduplicated and
cleaned after processing. The direct CLI supports `--summary-only` for a single
machine-readable JSON result.
