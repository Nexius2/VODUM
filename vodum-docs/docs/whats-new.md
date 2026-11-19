# Recent features

This page summarizes the current source tree. It is not a release announcement:
features may require updating your installed VODUM. Back up before upgrades;
startup applies the database bootstrap needed by new features.

## Collections

[Collections](collections.md) now has its own workspace, with reusable
configurations, preview, run history, scheduling and optional Sonarr/Radarr
acquisition. Sources include TMDb, IMDb, MyAnimeList, AniList and regional
streaming platforms. See the [model and source guide](collection-sources.md).

The dashboard counts configurations as **Successful** or **To review**. A
configuration is successful when every selected library has a successful last
synchronization. Missing titles and pending ARR acquisition can coexist with a
successful publication; review the per-library details to distinguish them.

## Monitoring

- The [user map](monitoring-map.md) explores playback locations, live state,
  server/country filters, heatmaps and historical playback over a selected period.
- [Library growth](library-growth.md) reports films/episodes and file size added
  over 7 days, 30 days or 1 year, alongside playback figures.
- Library rankings load separately when visible; the overview displays navigation
  and live information before loading historical rankings.
- Usage-risk recommendation history is refreshed by scheduled work, rather than
  being written when an administrator opens a report.
- Cached artwork can remain visible while a refresh runs in the background.

## Portal and requests

The [user portal](user-portal.md) includes provider authentication, personal
profiles, renewal information, invitations when enabled, support, personal
monitoring and system status. On phones, the main actions are available in a
bottom navigation bar, with a menu for additional enabled sections.

[Media requests](media-requests.md) search movies and series and submit to the
configured ARR route. Submission is queued; recent requests show waiting,
verification and final results across reloads. An accepted request is not a
confirmation that the media has already downloaded.

## Administration and communications

- Mobile administration has quick navigation, larger controls and user cards.
- Plex server suggestions load after the server list instead of blocking it.
- [Security settings](settings.md#security) group administrator access, Plex
  authentication, two-factor authentication and web security.
- [Communication channel choices](communications.md) follow the configured
  channels while preserving an existing selection until explicitly replaced.
- [Subscription gifts](subscriptions.md#gifts) retain their current history during
  temporary refresh failures and refresh while the page is in the foreground.

## Background work and responsiveness

Monitoring has a dedicated serial worker lane, separate from general work and
collections. Portal media requests have their own durable queue. Restore waits
for running work and suspends new starts until restart.

User and server lists avoid unnecessary joins; public assets avoid authentication
settings reads. These are implementation improvements, not production latency
guarantees. See [Performance](performance.md) for measurement tools and remaining
sources of waiting.

## Upgrade notes

Deploy Python, templates and static files together and restart the application.
The bootstrap creates the storage required for media-request jobs, persisted
collection results and library-growth snapshots. Allow the first growth task
and collection synchronization to finish before interpreting missing results.
A failed refresh preserves the last usable measurement when one exists.
