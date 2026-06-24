# Tasks

VODUM uses a deduplicated, strictly sequential application queue. A task may be
enabled, disabled, idle, queued, running or in error.

The Tasks page shows schedule, last/next run, attempts, status and error details.
**Run now** queues work; it does not start a second concurrent copy.

Task families include provider synchronization, server checks, user status and
expiration, access workers, Communications, monitoring refresh, backups,
retention, integrity checks, artwork cache, telemetry and migration support.

The global scheduler switch controls scheduled execution. Provider access jobs
remain durable in SQLite and are processed by their workers. On restart VODUM
recovers stale queued/running state conservatively.

If a task does nothing, verify it is enabled, its prerequisites exist and no
earlier long-running task is occupying the sequential worker. Then inspect Logs.
