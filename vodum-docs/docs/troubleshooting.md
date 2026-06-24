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
