# Architecture

VODUM is a Flask application served by Waitress with SQLite as durable state.
The container initializes/migrates the database before the centralized application
startup sequence, including repairs and background services.

## Boundaries

- Routes and templates validate requests and render state.
- Core services contain provider-neutral business rules.
- Provider adapters encapsulate Plex/Jellyfin/ARR behavior.
- Tasks and workers perform scheduled/queued external work.
- DBManager provides transaction-safe access and audited isolated read snapshots.
- The administration and portal have separate layouts, roles and resource contracts.

## Read and write paths

Monitoring pages primarily use collected snapshots in SQLite. Explicit read-only
builders can use separate SQLite connections without holding the shared writer's
Python lock. Multi-step mutations retain their transaction path; no authorization
cache replaces session/revocation checks.

Not every GET is purely local: examples include provider artwork fetching,
authenticated Plex discovery and portal search. Those paths must retain their
own origin, permission and resource restrictions. Durable provider mutation
workflows run through their designated workers where implemented; do not infer
that every action in the application is asynchronous.

## Background lanes

General work, collections and monitoring have distinct serial worker lanes.
The monitoring lane handles collection of live state, queued refreshes and stream
enforcement without waiting behind unrelated general or collection work. Portal
media-request jobs additionally use their own durable, single-job worker.

Different lanes can overlap. A lane still serializes its work, and SQLite and
provider rate limits remain shared constraints. The global scheduler controls
scheduled starts; the per-feature queue/worker lifecycle also matters.

## Recovery and restore

Startup performs explicit recovery, one-shot repairs and non-fatal provider
services. Durable work can recover eligible stale state. Uncertain ARR additions
are not blindly replayed. Restore waits for active work and suspends new starts
until restart; restored pending portal requests are closed to avoid duplicate
external additions. See [Backup](backup.md) and [Tasks](tasks.md).
