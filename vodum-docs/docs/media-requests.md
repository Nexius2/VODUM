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
5. Test with an account that actually has access to a routed library.

## Requests through Seerr

Add the Seerr server with its URL and API key in [Servers & libraries](servers-libraries.md);
VODUM detects Overseerr and Jellyseerr automatically. A Seerr server needs no
quality profile or destination folder: Seerr applies its own defaults, quotas
and approval rules. Optionally flag the server so that portal requests ask for
the 4K version.

Assign the Seerr server as a request route on the destination libraries, exactly
like an ARR. One Seerr instance can serve movie and series libraries at the same
time, and the same routing conditions (genres, collections) apply. A library may
route to Sonarr/Radarr or to Seerr; when both kinds of routes exist for a user,
the search results carry their origin and each request follows the route it came
from.

Requests are submitted **on behalf of the member**: VODUM looks up the Seerr user
whose Plex id (or Jellyfin id) matches the member's media account. A member who
never signed in to Seerr receives a clear message and nothing is sent. Seerr
then decides whether the title is already available or requested, applies the
member's quota and, if needed, keeps the request waiting for an administrator's
approval; the portal shows that outcome. VODUM does not scan libraries itself
for Seerr routes.

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
check, but an unconfirmed candidate is not enough to declare a title present. An
inaccessible service can block an addition when duplicate safety cannot be
established. For Seerr routes, the status reported by Seerr decides.

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
