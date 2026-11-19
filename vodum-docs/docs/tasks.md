# Tasks & background work

The Tasks page shows schedule, last/next run, attempts, status and error details.
**Run now** queues work rather than guaranteeing that it starts immediately.
Deduplication and worker leases prevent an extra copy of the same guarded work.

## Worker lanes

| Lane / worker | Work |
| --- | --- |
| General | Ordinary scheduled synchronization, communication and maintenance tasks |
| Collections | Collection inventory/publication work assigned to that lane |
| Monitoring | Live collection, queued refresh processing and stream enforcement |
| Portal media requests | Durable movie/series request verification and ARR submission, one job at a time |

Work in different lanes can run concurrently; each serial lane can still wait
behind its current job. The dedicated monitoring lane avoids making live updates
wait behind unrelated imports or campaigns. This is not unlimited provider or
SQLite concurrency.

## New data and recurring work

Library-growth measurements are refreshed daily. Usage-risk recommendation
history refreshes every 30 minutes; merely opening a report does not persist a
recommendation. New recurring tasks are added by startup bootstrap when required.
Check the scheduler, task enablement and prerequisites before expecting results.

The global scheduler switch controls scheduled execution. Feature queues are
persistent where implemented and recover eligible stale state on restart.
A provider refresh failure can be recorded as an error even if the last good
snapshot remains visible; an empty successful collection is still a success.

## When work stays queued

1. Check the global scheduler, task enablement and schedule.
2. Check the relevant lane and currently running job.
3. Check provider availability, configured credentials/defaults and cooldowns.
4. Inspect the detailed result and [Logs](logs.md) before retrying.

The optional [performance measurements](performance.md) distinguish HTTP waiting
from supported media-job queue waiting. Restoring a backup waits for running work
and suspends new starts until restart. Do not manually restart a provider addition
that is already recorded as uncertain without checking its external result.

## Expiration deletion and unavailable servers

Before deleting expired accounts, VODUM checks the native API for every linked
account. Connection failures, timeouts and HTTP 502/503/504 defer the deletion:
an INFO log identifies the unreachable server and retained user. These deferrals
alone do not fail the task. The server is checked again on the next scheduled run;
other users on that unavailable server are deferred without repeating the failed
request within the same run. Other reachable servers can still be processed.

Local records remain until every native deletion is confirmed, including after a
partial remote deletion. Authentication, TLS certificate and protection errors
remain failures requiring attention. Unreachable can also mean a network or proxy
problem; it does not prove that the server is powered off.
