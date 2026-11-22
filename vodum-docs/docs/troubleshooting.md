# Troubleshooting

## First checks

1. Open **Tasks** and identify queued/running/error work.
2. Open **Logs**, filter by source and download anonymized logs if needed.
3. Check `docker compose logs vodum` for entrypoint/startup errors.
4. Confirm database, logs, backups and encryption key are persistent.

## Common symptoms

**Server offline:** verify URL from inside Docker, token/API key, TLS and redirects.

**Access unchanged:** inspect provider jobs, run the relevant worker and then
synchronize the provider to confirm final state.

**Messages not sent:** test channel configuration, inspect Communications
history and verify recipient email/Discord identity.

**Now Playing delayed:** inspect the task queue and monitoring refresh tasks. A
bounded stale fallback is expected while the sequential queue is busy.

**Restore fails:** verify archive format, encryption-key compatibility, free
space and ZIP limits. Keep the original backup unchanged.

**Locked out:** use the documented password reset marker from the host and
restart the container; never expose the marker path publicly.

## Slow navigation or a loading section

Use the [performance guide](performance.md) to separate Flask work, SQLite lock
wait, HTTP worker wait and provider calls. The monitoring overview and Plex
suggestions intentionally load some sections after the first document. Inspect
the section result or retry it before interpreting it as an empty dataset.

For queued requests, inspect [media request results](media-requests.md) and the
appropriate [worker lane](tasks.md). Do not replay an uncertain ARR addition
without verifying whether the media was already added.

## Missing growth or collection status

[Library growth](library-growth.md) needs a completed measurement task and can
retain an older snapshot after failure. A collection needs a recorded per-library
synchronization result; absent history is not a successful run. Check the timestamp,
configuration and [collection history](collections.md#understand-the-result).
