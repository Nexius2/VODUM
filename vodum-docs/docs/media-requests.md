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
candidate is not enough to declare a title present. An inaccessible service can
block an addition when duplicate safety cannot be established.

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
