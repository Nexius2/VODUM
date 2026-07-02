# Servers & Libraries

## Add a server

Provide a unique name, provider type, reachable URL and token/API key. VODUM
validates the provider before saving it. Plex validation also checks the account
token against plex.tv, not only the local server.

You may configure local and public URLs. Redirects are accepted only when their
destination matches an explicitly configured server origin, preventing token
forwarding to unrelated hosts.

## Synchronization

- Plex synchronization imports server metadata, libraries, users and shares.
- Jellyfin synchronization imports native users, libraries and current access.
- Server checks update availability and temporary cooldown state.

Library access can be changed per user or through bulk grant/remove actions.
Provider operations are queued and deduplicated; review Tasks and Logs when a
change remains pending.

Deleting a server cascades its local provider data. Create a backup first and
confirm no migration campaign still depends on it.
