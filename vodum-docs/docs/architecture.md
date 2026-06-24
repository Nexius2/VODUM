# Architecture

VODUM is a Flask application served by Waitress with SQLite as its durable
state. The container entrypoint initializes/migrates the database before Flask
registers routes and runs the centralized startup sequence.

## Boundaries

- **Routes/templates** validate requests and render state.
- **Core services** contain provider-neutral business logic.
- **Providers** encapsulate Plex/Jellyfin API behavior.
- **Tasks** perform scheduled or queued external work.
- **DBManager** provides SQLite access and transaction-safe helpers.

Provider mutations are queued rather than performed by GET routes. Monitoring
pages read snapshots from SQLite. The sole audited GET exception is the
authenticated artwork proxy, which fetches provider images into a local cache.

Startup runs admin recovery, maintenance recovery, one-shot repairs and the
non-fatal Plex websocket engine as explicit ordered steps.
