# Migrations

Migrations move users and selected access between supported source and
destination servers through a controlled campaign.

The menu and migration endpoints are available only when the configured servers
contain at least one eligible pair: Plex and Jellyfin, two distinct Jellyfin
servers, or two Plex servers with identified, different owner accounts. Two
Plex servers belonging to the same account already share that account's users
and do not enable migrations. Unknown Plex owners do not count as different:
synchronize the servers first. ARR connections do not count as media servers.

This menu check reads local configuration without contacting providers. A
temporary outage does not hide an otherwise eligible configuration, but both
servers must be online for pair analysis and execution. Direct URLs cannot
bypass the configuration check. Pair eligibility is also rechecked when a
queued migration user is processed. Existing campaigns and reports are retained
in the database even if the workspace becomes unavailable.

## Safe workflow

1. Create a draft and choose source/destination servers.
2. Run analysis and resolve blockers or manual mappings.
3. Review the generated, secret-free plan.
4. Start the campaign and monitor per-user phases.
5. Pause, resume or retry failed users when necessary.
6. Validate invitations before removing source access.
7. Export the report for audit.

Campaigns are destination-locked to prevent conflicting concurrent work. Plex
invitation checks are retried and normalized. Source access is removed only
after validation and is stored in snapshots so it can be restored.

!!! danger
    Test on a small cohort first. Large-instance Plex/Jellyfin campaigns and
    destructive automation still require validation against real servers.

Current rollback restores captured source access. A destination-only rollback
that removes only campaign-added access remains future work.
