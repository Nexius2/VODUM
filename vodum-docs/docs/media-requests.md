# Media requests

The portal can let users search for movies and series and request missing titles
through Sonarr or Radarr, or through a Seerr instance (Overseerr or Jellyseerr).
The administrator controls whether this section is available and which
libraries/services can receive requests.

## Configure requests

1. Add a compatible Radarr server for films and/or Sonarr server for series in
   [Servers & libraries](servers-libraries.md).
2. Save the service's request defaults, including the choices required by its
   configuration, such as destination folder and quality profile.
3. Set the compatible request route on the user's destination media library.
4. Enable **Media requests** in the portal section settings. The control is
   unavailable until at least one ARR has saved request defaults or one Seerr
   server exists.
5. In the **Media request settings** card, choose **VODUM (Sonarr / Radarr)**
   or **Seerr (Overseerr / Jellyseerr)**. VODUM remains the default after upgrade.
   Only the selected engine is searched and receives requests. Switching engines
   invalidates old selections and queued jobs from the previous engine before a
   new submission; it does not cancel requests already sent.
6. Set **Number of recent requests shown** from 1 to 100 (default 10).
   This limit applies per portal account, on page load and during polling.
   Active jobs appear first; completed jobs remain in history for seven days.
   Changing the visible count does not change retention or delete requests.
7. Test with an account that actually has access to a routed library.

## Requests through Seerr

Add the Seerr server with its URL and API key in [Servers & libraries](servers-libraries.md);
VODUM detects Overseerr and Jellyseerr automatically. A Seerr server needs no
quality profile or destination folder: Seerr applies its own defaults, quotas
and approval rules. Optionally flag the server so that portal requests ask for
the 4K version.

On the Seerr server page, tick the libraries whose members may request through
it. That is the only routing decision for Seerr: it serves movie and series
libraries alike and picks the Radarr/Sonarr target, profile and folder itself.
Seerr requires an explicit enabled library association: without one, its
members cannot request through Seerr. ARR and Seerr associations may coexist;
only the engine selected by the administrator in portal settings is used.
The Seerr option can be saved only when a Seerr server exists; VODUM requires
at least one ARR with saved request defaults when requests are enabled.

Requests are submitted **on behalf of the member**: VODUM looks up the Seerr user
whose Plex id (or Jellyfin id) matches the member's media account. A member who
never signed in to Seerr receives a clear message and nothing is sent. Seerr
then decides whether the title is already available or requested, applies the
member's quota and, if needed, keeps the request waiting for an administrator's
approval; the portal shows that outcome. VODUM does not scan libraries itself
for Seerr routes.

Search results from Seerr carry its own status for the title: **Available**,
**Partially available** or **Already requested**, for the regular copy and,
when Seerr tracks one, for the 4K copy. Members then choose per request:

- **4K.** When the member's Seerr user holds the *Request 4K* permission (or
  its movie/series variant), the card offers a 4K checkbox preset to the
  server's 4K flag. Without that permission the server flag applies as before;
  a hidden or manually changed field cannot bypass the permission check, which
  is repeated when the request is submitted.
- **Seasons.** Requesting a series opens a season picker read from Seerr.
  Every season not yet available is preselected; seasons already available or
  in progress are shown locked. Specials are not offered. Without JavaScript,
  or if the season list cannot be loaded, the whole series is requested, which
  Seerr resolves to the seasons still missing.

After submission the recent-request list follows the Seerr request itself:
*waiting for approval*, *approved* (being processed), *partially available*,
*available*, *declined by an administrator*, *failed* (Seerr could not process
it) or *removed* when the request no longer exists in Seerr. A season request
is judged by the seasons it asked for, not by the show-wide status, which
stays partial as long as other seasons are missing. The state is read from Seerr when the page loads or
polls, at most once a minute per request and within a short deadline, so a
slow Seerr only delays the update. The list keeps the last known state while
Seerr is unreachable and stops following a request once it is available,
declined or removed; entries leave the list after 24 hours as usual.

Access is checked on the server. A hidden or manually changed browser field
cannot grant access to another user's library or an unrelated ARR instance.

## Submit a request

Search for a movie or series, inspect the result and submit it. Search still
waits for its source response; submission itself returns once the job is queued.
The recent-request list follows waiting, verification and the final result, and
survives a page reload. Successful submission does not mean the media is already
available for playback.

For ARR routes, the worker checks local media and compatible ARR entries by
external identifiers to avoid duplicates. Local inventory can accelerate the
check, but an unconfirmed candidate is not enough to declare a title present.
Unavailable verification services are skipped. An addition requires a reachable
eligible destination. For Seerr routes, the status reported by Seerr decides.

## Queue limits and interrupted work

The queue accepts at most **32 active jobs globally**, including at most **3 per
portal account**. A dedicated worker handles one job at a time. Recent results
are displayed for 24 hours and retained for 7 days.

A verification interrupted before addition can resume. If execution stops after
an ARR or Seerr addition has started, the outcome can be marked uncertain: VODUM
does not automatically replay that POST. Inspect ARR and the result before requesting
again. Pending jobs restored from a backup are closed to avoid replaying an
addition that may already have happened.

## If a request does not complete

Check the recent result first. The administrator should then inspect ARR
availability, saved defaults, library routing, the user's current access and
[Tasks](tasks.md). A global scheduler change, server outage or queue backlog
can affect processing. Never publish API keys or provider URLs in user-facing
support messages.

### Unavailable servers and destination failover

VODUM checks every registered compatible ARR and media library for duplicates.
A confirmed existing title still returns present/pending without posting another
addition. A failed check on an unavailable instance is logged as WARNING and
skipped, whether that instance is unrelated or linked as a secondary route.
The selected Plex/Jellyfin library being unavailable no longer prevents submitting
a request to a reachable ARR. A title present only on an unavailable instance
cannot be detected by that check.

Destination selection preserves library preferences, ARR priorities and media
criteria. If the highest-priority eligible ARR fails its inventory check, VODUM
tries the next reachable eligible destination. If it passes that check but its
quality-profile/root-folder API reads fail, VODUM may also try the next destination
before submission. Invalid saved defaults remain a configuration error, rather
than silently overriding the administrator's configuration.

The account/library permissions are checked before submission. Once an addition
POST has started, its failure or uncertain response is never replayed on another
instance: the first instance may already have accepted it. Only pre-submission
read failures permit failover. If no eligible destination is available, the portal
reports `portal_requests_no_arr_available`. Previous result keys and historical
records are preserved.

A green status test and an inventory request such as `GET /api/v3/series` are
separate operations. Check `Media request API connection failure` / `Media request
API failure` warnings and the destination/skip messages for the relevant server
IDs. Errors are reserved for an unavailable final destination or failed addition.
**Download logs** exports all retained levels with anonymization, independently
of the selected UI filter. Earlier builds could block a request on any registered
ARR failure and logged `ARR duplicate verification blocked`; this policy was
replaced on 2026-11-22 with skip-and-continue behavior.
