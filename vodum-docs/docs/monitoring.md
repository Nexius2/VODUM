# Monitoring

Monitoring is built from provider snapshots stored in SQLite; normal pages do
not call Plex or Jellyfin directly.

## Tabs

- **Overview** — aggregate users, servers, watch time and top media.
- **Location** — [user map](monitoring-map.md), live filters, heatmap and historical timeline.
- **Now Playing** — live sessions, progress, playback decisions, video quality
  and artwork. The quality line shows the source (resolution, codec, HDR or
  Dolby Vision) and, when the video is transcoded, the quality sent to the
  player, for example `4K HEVC HDR → 1080p H.264`.
- **Activity** — time-based playback trends.
- **History** — completed sessions and session details.
- **Libraries** — playback, [library growth](library-growth.md) and deferred media rankings.
- **Users** — watch activity and usage per user.
- **Servers** — activity and availability by server.
- **Usage risk** — repeated IP/device patterns and suggested plan upgrades.
- **Policies** — active rules and paginated enforcement history.
- **User portal** — portal usage when the portal is enabled.

Collector delays do not immediately delete Plex sessions. Missing sessions are
confirmed across bounded refreshes, and a recent snapshot fallback is only used
while the processing pipeline is genuinely busy.

## Policy scope

Policies may target a user, server or global provider context. Available rules
include stream/IP limits, server transcode limits and 4K-transcode blocking.
Violations can warn or stop playback. Test new rules with conservative limits
and review enforcement history before broad rollout.

## Loading and freshness

Overview renders navigation, server state and live counts before its historical
rankings load. The library table also appears before its most-watched-title
section, which loads when visible. A loading placeholder is not a final zero.
Historical aggregates reuse recent results; current collection delays can leave
the last good snapshot visible.

Automatic refresh pauses when the page is hidden and resumes on return. The
cached artwork proxy can show a previous image while refreshing it in the
background. Historical computation and remote image retrieval can still take
time; see [Performance](performance.md) to distinguish them.

## Usage-risk recommendations

Reports calculate the current filtered suggestions on read. A scheduled task
refreshes recommendation history every 30 minutes, and the sender checks
eligibility again before notification. Opening a report does not itself persist
or send a recommendation. Location or shared IP observations alone are not proof
that accounts are being misused.
