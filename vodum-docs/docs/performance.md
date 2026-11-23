# Performance & response times

Slow navigation can come from page computation, a busy background worker,
SQLite contention, external services, image downloads or the network path.
Measure them separately before increasing concurrency or changing storage.

## Expected loading behavior

- User lists load a page before enriching its roles/access counts for simple
  sorts. Sorting by a count or subscription still considers all candidates.
- Server cards count libraries and users separately.
- Plex discovery suggestions load after the server list and can be retried.
- Monitoring Overview displays navigation and live information before its
  historical rankings. Libraries load their rankings separately when visible.
- Existing cached artwork can be served while a bounded background refresh runs.
- Hidden monitoring pages pause automatic refresh; returning to the page resumes it.

A loading placeholder is not a final zero. Historical aggregates can still take
time on a large or cold database. These behaviors do not establish a guaranteed
production response time.

## Route timing

Slow-route measurements are enabled unless `VODUM_ROUTE_TIMING=0`. The default
logging threshold is 300 ms. Optional fields can be enabled in the container
environment before restarting:

```env
VODUM_ROUTE_TIMING=1
VODUM_ROUTE_TIMING_THRESHOLD_MS=300
VODUM_SQLITE_TIMING=1
VODUM_PROVIDER_CACHE_TIMING=1
VODUM_WAITRESS_QUEUE_TIMING=1
VODUM_MEDIA_JOB_QUEUE_TIMING=1
```

| Measurement | What it distinguishes |
| --- | --- |
| Route duration / `Server-Timing: app` | Flask handling, including authentication hooks |
| SQLite timing | Shared-lock wait, instrumented SQL time and call count |
| Provider/cache timing | Instrumented provider HTTP and aggregate-cache activity in the request context |
| Waitress timing | Waiting for an available HTTP worker, separately from Flask execution |
| Media job queue timing | First eligible wait for monitoring-refresh and Plex-access jobs |

Provider/cache timing does not cover every network operation outside the
instrumented request path. Direct SQLite access outside DBManager is not included
in its timings. HTTP worker waiting excludes request-body reception and response
transfer. Retried media jobs and other queues are outside the job wait sample.

## Read a capture

The application includes `app/route_timing_report.py`. From the VODUM source root:

```bash
python app/route_timing_report.py /path/to/capture.log --by-view
python app/route_timing_report.py /path/to/capture.log --media-jobs
```

The CSV reports p50/p95/p99 and sample counts. `--by-view` distinguishes monitoring
tabs and the deferred library ranking request. With the default threshold, the
capture contains slow requests only: its percentiles are not the latency
percentiles of all traffic. Use a threshold of zero for a bounded all-request
capture when necessary, then restore the normal threshold.

Compare the same routes, filters, volume and cache state before/after a change.
A fast warm request does not establish a fast first request. Keep logs private;
performance records use endpoint names rather than concrete token-bearing URLs.

## Diagnose before tuning

1. Compare the browser's document timing with image and asset requests.
2. Check whether the delay is HTTP queue wait, lock wait, SQL or external I/O.
3. Check the relevant task lane and provider state in [Tasks](tasks.md).
4. Confirm that database and persistent directories are writable and suitable
   for SQLite; do not remove its locks or move a live database casually.
5. Tune `VODUM_WAITRESS_THREADS` only after identifying worker saturation.
   More workers do not make an expensive query or an unavailable provider faster.

## Initial Collections page

The first Collections page load reads libraries, compatible ARR routes,
configurations and settings from one read-only SQLite snapshot. ARR routes are
loaded together instead of once per library. This reduces contention with
background writes while preserving the displayed data and ordering. The polling
API still uses its existing recovery path; this change applies to the initial
page load. Production latency still depends on the database and concurrent work.

## Persisted historical Monitoring statistics

`refresh_monitoring_statistics` checks for work every minute. Completed historical
views are stored in `monitoring_precomputed` and survive restarts. Results become
eligible for refresh after five minutes; this is a freshness target, not a
completion deadline when the queue or database is busy.

The prepared views now cover:

- Overview, library totals and library rankings.
- History and Users, including normalized searches, sorts and pages.
- Server historical statistics and ARR history, by period.
- Activity charts and the daily chart of a media-user profile.
- Policy historical summaries, charts and paginated enforcement records.
- Usage-risk reports and Portal usage statistics, by filters and period.
- Historical map observations, including a selected timeline instant/server.

Eleven default views are seeded idempotently during startup. A different period,
search, sort, page or timeline instant registers a bounded background request.
Its first opening displays a preparation notice. Pages never fall back to the
heavy historical builder on a miss. Current data is retained during refresh and
after a failure, with a UTC computation timestamp and a warning if stale/failed.
Changing filters may therefore require waiting for the next available task run.

Live sessions/progress, server availability, resource percentages, current ARR
queue/health samples, portal online counts, policy tracking state and the recent
activity feed remain on current reads. Server historical totals now describe
completed playbacks; ongoing playbacks are shown separately in the live counters.
The map combines prepared history with current session observations and keeps
live points visible during initial historical preparation. Its live-only mode
continues to use current reads without waiting for a historical view.

Timeline requests preserve their exact instant and anchor their time window with
`until`, so a pending earliest instant does not move as time passes. Playback
waits for each prepared instant before advancing. Interactive charts expose
pending results as HTTP 202 with a retry delay; they retain their previous data
while waiting, show the computation timestamp and stop waiting on navigation.
Queue saturation returns HTTP 429 rather than presenting an empty chart.

Calculations use a separate read-only SQLite snapshot. Each completed view is
published by a short atomic write, in the general task lane rather than the live
monitoring lane. A run checks at most 12 eligible views and has a 90-second SQL
progress budget. The store is capped at 128 entries, including defaults. Custom
views are refreshed while recently requested and removed after seven days of
inactivity. The default views are retained.

Deploy Python modules, templates and JavaScript together, then restart VODUM.
Bootstrap registers the additional default views in the existing table; no new
schema table is required for this extension. Wait for the task or run **Refresh
historical monitoring statistics** from Tasks. The existing global scheduled-task
switch and the task's own enabled setting remain authoritative.

This moves the existing builders off HTTP requests; it does not incrementally
maintain every ranking. The task reuses compact daily aggregates where applicable
and otherwise recalculates a view. It still consumes CPU and storage I/O. Individual
record/detail lookups, configuration/authorization checks and operational actions
keep their direct paths. Configurations used for policy editing and the Portal
access check are read afresh rather than trusted from historical payloads.

The initial local test on 50,002 history records and three libraries measured
170 ms for the library calculation against 7 ms for the prepared read, with equal
rows. That measurement is for the library builder/read path, not a guarantee for
all tabs, the browser or the Unraid deployment.

Failed statistics runs now name the failed view and safe cause category in the
scheduler error, rather than only reporting a count. The detailed
`monitoring.refresh_snapshot` operation record is also ERROR and carries the view
key under `object_title`. `sql_budget_exceeded` means SQLite interrupted work at
the run deadline; it does not identify a database corruption. Missing-table and
missing-column categories indicate a schema mismatch to investigate. Existing
results stay readable. Download the current full log to diagnose an older generic
`Monitoring snapshot(s) failed` entry; the screenshot alone does not establish its
cause.
