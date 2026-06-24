# VODUM documentation

VODUM is a self-hosted administration layer for Plex and Jellyfin. It combines
users, subscriptions, library access, monitoring, policies, communications,
migrations, backups and scheduled work in one authenticated interface.

!!! warning "Beta software"
    Back up VODUM before every upgrade. Plex support is currently more mature
    than Jellyfin support. Validate destructive workflows against your own
    servers before enabling them in production.

## Start here

1. [Install VODUM and complete first-run setup](getting-started.md).
2. [Add and validate media servers](servers-libraries.md).
3. [Synchronize users and libraries](users.md).
4. [Configure subscriptions](subscriptions.md).
5. [Review scheduled tasks](tasks.md).
6. [Create a full backup](backup.md).

## Application sections

| Section | Purpose |
|---|---|
| [Dashboard](dashboard.md) | Operational summary and current activity |
| [Monitoring](monitoring.md) | Live sessions, history, usage risk and policies |
| [Users](users.md) | Identities, access, expiration and account actions |
| [Servers & Libraries](servers-libraries.md) | Provider connections and library inventory |
| [Subscriptions](subscriptions.md) | Plans, assignment and renewal workflows |
| [Communications](communications.md) | Email, Discord, templates, campaigns and history |
| [Migrations](migrations.md) | Controlled user/access migration campaigns |
| [Backup & Import](backup.md) | Backup, restore and Tautulli import |
| [Settings](settings.md) | Global behavior, security and automation |
| [Logs](logs.md) | Anonymized operational diagnostics |
| [Tasks](tasks.md) | Scheduler state and manual execution |

For deployment security, read [Security](security.md) before exposing VODUM
through a reverse proxy.
