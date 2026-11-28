# FAQ

## General

**Does VODUM replace Plex or Jellyfin?**
No. VODUM manages users, subscriptions and access on top of your existing servers.

**Can I use Plex and Jellyfin together?**
Yes. VODUM manages several Plex and Jellyfin servers at once, and one person can
have accounts on several of them.

**Does Jellyfin have every Plex feature?**
Most features work on both. Some depend on what the server allows: for example,
Jellyfin cannot sort a collection in a custom order. Test a workflow on a few
users before using it widely.

## Users and subscriptions

**Are users deleted when their subscription expires?**
It depends on the expiration mode of the plan: VODUM can just track the status,
warn the user, or remove their access. See [Subscriptions](subscriptions.md#start-and-expiration).

**I changed access but nothing happened on the server.**
Changes are sent by a background task. Check [Tasks](tasks.md) and see
[Troubleshooting](troubleshooting.md#common-problems).

**Why did a button only "queue" the work?**
Actions that change Plex, Jellyfin or Sonarr/Radarr run in the background, so the
page does not freeze and the work can be retried if a server is busy. Follow
them in [Tasks](tasks.md).

## Administration

**I forgot my administrator password.**
See [Locked out of administration](troubleshooting.md#locked-out-of-administration).

**Which backup should I keep?**
The full ZIP: it contains everything needed to restore. A database-only backup
also needs the encryption key file. See [Backup & import](backup.md).

**Can I open VODUM to the internet?**
Only behind an HTTPS reverse proxy, after following the [Security](security.md)
checklist. The user portal can be public while administration stays private.

**Where can I get help?**
On the [Discord community](https://discord.gg/5PU7TnegZt) or on
[GitHub](https://github.com/Nexius2/VODUM). Include the version shown in **About**
and the anonymized logs.
