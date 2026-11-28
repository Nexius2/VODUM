# What's new

This page summarizes the current source tree. It is not a release announcement:
features may require updating your installed VODUM. Back up before upgrades;
startup applies the database bootstrap needed by new features.

## Compliance

[Compliance](server-configuration.md) shows each setting of your Plex and
Jellyfin servers once, with the values of all the servers, and keeps reference
profiles. It checks that servers follow them, shows the values recommended by
Plex and Jellyfin, and, in manual remediation only, fixes or deploys settings
after a preview and your confirmation. It only reads your servers by default.

## Dashboard API

A read-only [Dashboard API](api.md) feeds Homepage, Grafana or your own
scripts with live playback, server, playback-detail and user counts. Create one
token per application in **Settings > API access**, choose what it may read,
and revoke it at any time. Tokens are shown once, limited to 60 calls per
minute, and never expose emails, IP addresses, server credentials or payments.

## Collections

[Collections](collections/index.md) now has its own workspace, with reusable
configurations, preview, run history, scheduling and optional Sonarr/Radarr
acquisition. Sources include TMDb, IMDb, MyAnimeList, AniList and regional
streaming platforms. See the [model and source guide](collection-sources.md).

The dashboard counts configurations as **Successful** or **To review**. A
configuration is successful when every selected library has a successful last
synchronization. Missing titles and pending ARR acquisition can coexist with a
successful publication; review the per-library details to distinguish them.

Franchise lists can follow a [chronological (story) order](collections/index.md#chronological-order-of-a-list).
VODUM lists include a reference order for the main continuity of 31 franchises,
and you can save your own order per list.

## Monitoring

- The [location map](monitoring-map.md) explores playback locations, live state,
  server/country filters, heatmaps and historical playback over a selected period.
- [Library growth](library-growth.md) reports the net change of films/episodes
  and file size over 7 days, 30 days or 1 year, between two scans. Media
  re-added by Plex or Jellyfin no longer count as new.
- Now Playing shows the video quality of each playback: the source and, when
  transcoded, the quality sent to the player.
- Historical tabs no longer show a "computed at" banner when their figures are
  up to date; a notice remains while figures are prepared, stale or failed.
- A server that misses one poll is retried after its 5-minute cooldown instead
  of staying "unavailable" until the next server check.
- Now Playing posters go ahead of background Plex work.
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

Administrators can set an optional request limit per user (per day, 7 days or
30 days). When Sonarr/Radarr's answer to a request is lost, VODUM checks that
instance for one day and shows whether the media was added. Seerr requests for
series without a TVDB id use Seerr's Sonarr lookup, asking the member to pick
when several series match.

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

Monitoring has its own task queue, so live updates no longer wait behind imports
or campaigns. Portal media requests have their own queue too, and a restore waits
for running tasks before replacing the data. Several lists and pages load faster.
See [Performance](performance.md) to measure response times.

## Upgrade notes

The Docker image now uses Python 3.14 on Debian 13 (trixie). Updating the
container is enough; if you build the image yourself, rebuild it from the
current Dockerfile.

On the first start after updating, VODUM prepares its database for the new
features. Library growth needs two daily scans, and collections need one run,
before their results appear.
