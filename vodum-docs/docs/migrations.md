# Migrations

Migrations move users and selected access between supported source and
destination servers through a controlled campaign.

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
