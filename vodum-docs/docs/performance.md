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
