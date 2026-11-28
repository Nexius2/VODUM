# Migrations

A migration moves users and their library access from one server to another,
for example from Plex to Jellyfin, step by step and with a report.

## When migration is possible

**Migrations** is always in the menu, in the **Servers** group. A migration needs
at least one possible pair of servers:

- a Plex server and a Jellyfin server;
- two different Jellyfin servers;
- two Plex servers owned by **different** Plex accounts (two servers of the same
  account already share their users). Synchronize them first so VODUM knows their owner.

Without such a pair, the page explains what migrations are for and why none is
possible yet. Sonarr, Radarr and Seerr do not count. Both servers must be online
to analyze and run a migration.

## Quick start

1. Create a draft and choose the source and destination servers.
2. Run the analysis, then fix what blocks and match users by hand where needed.
3. Review the plan.
4. Start the migration and follow each user's progress.
5. Pause, resume or retry failed users if needed.
6. Check that invitations were accepted before removing access on the source.
7. Export the report.

!!! danger "Test first"
    Start with a few users. Large migrations and automatic removals still need
    to be validated on real servers.

## Safety

Only one migration can target a destination server at a time. Access on the
source server is only removed after validation, and VODUM keeps a copy so it can
be given back. Undoing only what was added on the destination is not available yet.
