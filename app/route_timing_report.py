"""Summarize route or media job timings from a selected VODUM log capture."""

import argparse
import csv
import re
import sys
from collections import defaultdict
from math import ceil


ROUTE_TIMING = re.compile(
    r"^[^|]* \| INFO \| vodum\.performance \| route_timing"
    r" \| duration_ms=(\d+) \| status=([1-5]\d\d)"
    r" \| method=(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|OTHER)"
    r" \| endpoint=([\w.-]+) \| htmx=([01])"
    r"(?: \| db_lock_wait_us=(\d+) \| db_sql_us=(\d+) \| db_sql_calls=(\d+))?"
    r"(?: \| waitress_queue_wait_us=(\d+))?"
    r"(?: \| provider_us=(\d+) \| provider_calls=(\d+) \| aggregate_cache_us=(\d+)"
    r" \| aggregate_cache_hits=(\d+) \| aggregate_cache_misses=(\d+))?"
    r"(?: \| view=([a-z_]+))?$",
    re.ASCII,
)
MEDIA_JOB_QUEUE = re.compile(
    r"^[^|]* \| INFO \| vodum\.performance \| media_job_queue"
    r" \| kind=(monitoring_refresh|plex_access) \| wait_s=(\d+)$",
    re.ASCII,
)


def percentiles(samples):
    samples = sorted(samples)
    if not samples:
        return ("", "", "")
    return tuple(samples[ceil(len(samples) * p / 100) - 1] for p in (50, 95, 99))


def summarize(lines, *, by_view=False):
    requests = defaultdict(list)
    for line in lines:
        match = ROUTE_TIMING.fullmatch(line.rstrip("\r\n"))
        if match:
            duration, status, method, endpoint, htmx, *metrics, view = match.groups()
            group = (endpoint, method, status, htmx)
            if by_view:
                group += (view or "",)
            requests[group].append((duration, *metrics))

    for group, samples in sorted(requests.items()):
        metrics = [[int(value) for value in column if value is not None] for column in zip(*samples)]
        durations, lock_waits, sql_times, sql_calls, queue_waits = metrics[:5]
        provider_times, provider_calls, cache_times, cache_hits, cache_misses = metrics[5:]
        yield (
            *group, len(samples), *percentiles(durations), len(sql_times),
            *percentiles(lock_waits), *percentiles(sql_times), *percentiles(sql_calls),
            len(queue_waits), *percentiles(queue_waits),
            len(provider_times), *percentiles(provider_times), *percentiles(cache_times),
            sum(provider_calls), sum(cache_hits), sum(cache_misses),
        )


def summarize_media_jobs(lines):
    waits = defaultdict(list)
    for line in lines:
        match = MEDIA_JOB_QUEUE.fullmatch(line.rstrip("\r\n"))
        if match:
            kind, wait = match.groups()
            waits[kind].append(int(wait))

    for kind, samples in sorted(waits.items()):
        yield (kind, len(samples), *percentiles(samples))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=argparse.FileType("r", encoding="utf-8", errors="replace"),
                        help="log capture, or - for standard input")
    parser.add_argument("--media-jobs", action="store_true", help="report media job queue waits")
    parser.add_argument("--by-view", action="store_true", help="group monitoring timings by tab")
    args = parser.parse_args()
    header = (
        "endpoint", "method", "status", "htmx", "count", "p50_ms", "p95_ms", "p99_ms", "db_count",
        "db_lock_wait_p50_us", "db_lock_wait_p95_us", "db_lock_wait_p99_us",
        "db_sql_p50_us", "db_sql_p95_us", "db_sql_p99_us",
        "db_sql_calls_p50", "db_sql_calls_p95", "db_sql_calls_p99",
        "waitress_queue_count", "waitress_queue_wait_p50_us", "waitress_queue_wait_p95_us",
        "waitress_queue_wait_p99_us",
        "provider_cache_count", "provider_p50_us", "provider_p95_us", "provider_p99_us",
        "aggregate_cache_p50_us", "aggregate_cache_p95_us", "aggregate_cache_p99_us",
        "provider_calls_total", "aggregate_cache_hits_total", "aggregate_cache_misses_total",
    )
    if args.media_jobs:
        rows = summarize_media_jobs(args.log)
        header = ("kind", "count", "p50_s", "p95_s", "p99_s")
    else:
        rows = summarize(args.log, by_view=args.by_view)
        if args.by_view:
            header = (*header[:4], "view", *header[4:])
    first = next(rows, None)
    if first is None:
        parser.exit(1, "No compatible timing samples in this capture.\n")

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(header)
    writer.writerow(first)
    writer.writerows(rows)


if __name__ == "__main__":
    main()
