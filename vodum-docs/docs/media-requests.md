# Media requests

The portal can let users search for movies and series and request missing titles
through Sonarr or Radarr. The administrator controls whether this section is
available and which libraries/services can receive requests.

## Configure requests

1. Add a compatible Radarr server for films and/or Sonarr server for series in
   [Servers & libraries](servers-libraries.md).
2. Save the service's request defaults, including the choices required by its
   configuration, such as destination folder and quality profile.
3. Set the compatible request route on the user's destination media library.
4. Enable **Media requests** in the portal section settings. The control is
   unavailable when the required ARR configuration is not ready.
5. Test with an account that actually has access to a routed library.

Access is checked on the server. A hidden or manually changed browser field
cannot grant access to another user's library or an unrelated ARR instance.

## Submit a request

Search for a movie or series, inspect the result and submit it. Search still
waits for its source response; submission itself returns once the job is queued.
The recent-request list follows waiting, verification and the final result, and
survives a page reload. Successful submission does not mean the media is already
available for playback.

The worker checks local media and compatible ARR entries by external identifiers
to avoid duplicates. Local inventory can accelerate the check, but an unconfirmed
candidate is not enough to declare a title present. Unavailable verification services are skipped. An addition requires a reachable
eligible destination.

## Queue limits and interrupted work

The queue accepts at most **32 active jobs globally**, including at most **3 per
portal account**. A dedicated worker handles one job at a time. Recent results
are displayed for 24 hours and retained for 7 days.

A verification interrupted before addition can resume. If execution stops after
an ARR addition has started, the outcome can be marked uncertain: VODUM does
not automatically replay that POST. Inspect ARR and the result before requesting
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
