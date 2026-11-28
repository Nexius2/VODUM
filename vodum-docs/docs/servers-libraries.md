# Servers & libraries

This is where you connect VODUM to your Plex and Jellyfin servers, and to the
Sonarr, Radarr or Seerr services used for requests.

## Quick start

1. Open **Servers & libraries** and add a server: its address and its Plex token
   or Jellyfin API key. VODUM checks them before saving.
2. Run **Plex sync** or **Jellyfin sync** in [Tasks](tasks.md) to import its
   libraries, users and shares.
3. Check the libraries and change user access where needed.

## Add a server

Enter an address that VODUM can reach and the token or API key. For Plex, VODUM
may also check the token with plex.tv.

If a Plex administrator account is linked, VODUM suggests the Plex servers of
that account. Check the owner and the connection before adding a suggestion.
If the suggestions fail to load, you can retry or add the server by hand.

You can set a local and a public address where supported. Redirects are only
followed to addresses you configured.

## Synchronization and access

- Plex sync imports the server, its libraries, users and shares.
- Jellyfin sync imports its users, libraries and current access.
- **Check servers** updates availability and the last check time.

Change library access per user, or for several users at once. Changes are sent
to the server by a background task: check [Tasks](tasks.md) before considering
a change done. When a library disappears from the server, its accesses are
removed from VODUM too.

## Sonarr, Radarr and Seerr

These services are used for [portal media requests](media-requests.md) and,
optionally, by [collections](collections/index.md) to download missing titles.

- **Radarr** handles films and **Sonarr** handles series. Add the service, save
  its request defaults (quality profile, root folder…), then choose it as the
  request route on each destination library. A server card warns you while
  the defaults are not saved.
- **Seerr** (Overseerr or Jellyseerr) is an alternative: add it with its API key,
  no defaults needed, and it can serve film and series libraries. Requests then
  follow Seerr's own profiles, quotas and approvals.

Routes are set per library: a user can only send requests to the services routed
to their own libraries.

## Tokens and deletion

Tokens and API keys are hidden; use the reveal button only when needed. Leaving
the field empty when editing keeps the saved value.

Deleting a server removes its data from VODUM (users' accesses on that server,
libraries…). It does not reset anything on the server itself. Before deleting,
create a full backup and check that no collection, request route or migration
still uses it.
