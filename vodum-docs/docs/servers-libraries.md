# Servers & libraries

## Add and discover a server

Enter the reachable server URL and its token/API key in **Servers**. VODUM
identifies and validates supported services before saving their configuration.
Plex validation can also require checking the account token with plex.tv.

If an administrator Plex identity is linked, VODUM can suggest available Plex
servers. Suggestions load after the server list; a discovery failure offers a
retry without preventing access to existing server cards or manual creation.
Review ownership, availability and the selected connection before adding a suggestion.

Local and public URLs may be configured where supported. Redirects carrying
credentials are restricted to explicitly configured origins; do not work around
validation by pasting an unrelated host.

## Synchronization and access

- Plex synchronization imports server metadata, libraries, users and shares.
- Jellyfin synchronization imports native users, libraries and current access.
- Server checks update availability and the last check time.

Change library access per user or with the supported bulk grant/remove actions.
Review pending jobs and provider state before treating a change as applied.
Identical metadata/access values avoid unnecessary rewrites. Removing a vanished
provider library removes its local grants transactionally; if local constraints
prevent cleanup, synchronization preserves those grants rather than half-deleting them.

## Sonarr/Radarr routing

ARR services support [portal requests](media-requests.md) and optional collection
acquisition. Add the service, save its request defaults and assign compatible
routes on the destination library. Radarr handles films and Sonarr handles series.
A server card can report incomplete request configuration until defaults are saved.

Routes are library-specific. The existence of an unrelated ARR server does not
authorize a portal user to send it requests or expose it in their system status.

## Tokens and deletion

Credential fields are masked; use the explicit administrative reveal control only
when needed. Blank credential edits preserve an existing stored secret according
to the form's behavior.

Deleting a server removes related local provider data. Read the confirmation,
create a full backup and verify that collections, routes and migration campaigns
no longer depend on it. A local delete is not a general-purpose provider reset.
