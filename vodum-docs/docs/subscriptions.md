# Subscriptions

Subscription templates define a plan name, duration, stream allowance and other
defaults. Templates can be enabled/disabled, duplicated, restored and assigned
to individual users or all users from a server.

Expiration can start immediately or on first playback. The first-playback mode
prevents unused invitations from consuming subscription time.

## Expiration modes

- **None** — status tracking without automatic access enforcement.
- **Warn only** — notify and apply the system expiration stream policy while
  keeping library shares.
- **Warn then disable** — warn for a configured grace period, then remove access.
- **Disable** — queue access removal when expiration is reached.

Renewal removes the system expiration policy and queues provider access
synchronization. Protected Plex owners and Jellyfin administrators are excluded
from normal subscription editing.

Always verify queued jobs and provider synchronization after bulk assignments.
