# FAQ

**Does VODUM replace Plex or Jellyfin?** No. It manages access and workflows on
top of those servers.

**Can one person use several servers?** Yes. A VODUM user can link multiple
provider identities.

**Are users deleted when subscriptions expire?** Normally access is changed;
provider accounts are preserved. Behavior depends on expiration settings.

**Why did a button only queue work?** External mutations are durable queued
jobs. This avoids blocking requests and permits retry/recovery.

**Is Jellyfin fully equivalent to Plex?** Not yet. Review release notes and test
provider-specific workflows before broad automation.

**Which backup should I use?** Full ZIP for self-contained restore; raw SQLite
only when the encryption key is preserved separately.
