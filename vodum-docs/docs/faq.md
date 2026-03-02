---
title: ❓ FAQ
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# ❓ FAQ

<span class="hint-badge">Subscriptions • Policies • Plex • Jellyfin • Tasks</span>

<br><br>

</div>


??? question "Does VODUM delete users?"
    No. The philosophy is to manage **access**, not deletion.

??? question "Why do I see a user in Policies but it shouldn't match?"
    Usually it’s an expiration date mismatch, merged user mapping, or a stale state that will be refreshed by the next task run.

??? question "Do tasks re-run missed executions after downtime?"
    VODUM is designed to avoid “catch-up storms”. After restart it should run safely without replaying hundreds of missed runs.

??? question "Can I run without Mailing/Discord?"
    Yes. You can manage subscriptions and access without notifications.

??? question "Where are backups stored?"
    In the configured backup directory (see Backup docs), usually under the persistent data volume.
