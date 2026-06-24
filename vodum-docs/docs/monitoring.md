# Monitoring

Monitoring is built from provider snapshots stored in SQLite; normal pages do
not call Plex or Jellyfin directly.

## Tabs

- **Overview** — aggregate users, servers, watch time and top media.
- **Now Playing** — live sessions, progress, playback decisions and artwork.
- **Activity** — time-based playback trends.
- **History** — completed sessions and session details.
- **Libraries** — activity grouped by media library.
- **Users** — watch activity and usage per user.
- **Servers** — activity and availability by server.
- **Usage risk** — repeated IP/device patterns and suggested plan upgrades.
- **Policies** — active rules and paginated enforcement history.

Collector delays do not immediately delete Plex sessions. Missing sessions are
confirmed across bounded refreshes, and a recent snapshot fallback is only used
while the processing pipeline is genuinely busy.

## Policy scope

Policies may target a user, server or global provider context. Available rules
include stream/IP limits, server transcode limits and 4K-transcode blocking.
Violations can warn or stop playback. Test new rules with conservative limits
and review enforcement history before broad rollout.
