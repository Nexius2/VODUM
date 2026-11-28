# Tasks

VODUM does most of its work in the background: synchronizing Plex and Jellyfin,
applying access changes, sending messages, running collections, backups and
cleanups. The **Tasks** page shows each task with its schedule, last and next
run, status and errors.

## Quick start

- **Run** a task now: it is added to the queue and starts as soon as possible.
- Turn a task on or off with its switch.
- Read the error of a failed task, then check the [Logs](logs.md).
- The global scheduler switch (in [Settings](settings.md#system)) turns all
  scheduled runs on or off.

## Useful tasks

| Task | What it does |
| --- | --- |
| Plex sync / Jellyfin sync | Import users, libraries and access from your servers |
| Apply Plex / Jellyfin access updates | Send pending access changes to the servers |
| Check servers | Check that servers are reachable (and compliance, if profiles are assigned) |
| Expired subscriptions manager | Apply the expiration mode of your plans |
| Run collections | Run the scheduled collections |
| Monitoring: collect sessions | Read current playback |
| Stream enforcer | Apply [stream policies](policies.md) |
| Automatic backup | Create backups |
| Refresh library growth statistics | Measure library growth, once a day |

## Why a task waits

Tasks are split into several queues so that a long job does not block everything:
general work, collections, monitoring, and portal media requests. Each queue runs
one job at a time, so a task can wait for the current job of its queue.

When a task stays queued:

1. Check the global scheduler and that the task is enabled.
2. Check which job is currently running in that queue.
3. Check that the server is reachable and its settings are complete.
4. Read the result and the [Logs](logs.md) before running it again.

Do not run again an addition to Sonarr/Radarr marked as *uncertain* before checking
whether the media was already added.

## Deleting expired accounts when a server is offline

Before deleting expired accounts, VODUM checks each linked account on its server.
If a server does not answer (connection error, timeout, HTTP 502/503/504), the
deletion is postponed to the next run and the logs name the server and the user.
This does not make the task fail, and reachable servers are still processed.
The VODUM user is kept until every deletion is confirmed. Authentication and
certificate errors are still reported as failures.
