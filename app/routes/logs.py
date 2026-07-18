import math
from datetime import datetime

from flask import Response, render_template, request

from logging_utils import AnonymizeFilter, parse_log_records, read_all_logs, read_logs_snapshot


ALLOWED_LOG_LEVELS = {"ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def normalize_log_level(value) -> str:
    level = str(value or "ALL").strip().upper()
    return level if level in ALLOWED_LOG_LEVELS else "ALL"


def summarize_log_levels(records) -> dict[str, int]:
    counts = {level: 0 for level in ALLOWED_LOG_LEVELS if level != "ALL"}
    for record in records:
        level = str(record.get("level") or "").upper()
        if level in counts:
            counts[level] += 1
    counts["ALL"] = sum(counts.values())
    return counts


def register(app):
    @app.route("/logs")
    def logs_page():
        # Default to the complete stream. The previous INFO default was an
        # exact filter and therefore hid WARNING/ERROR/CRITICAL incidents.
        level = normalize_log_level(request.args.get("level"))
        search = request.args.get("q", "").strip()
        try:
            page = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        per_page = 200

        snapshot = read_logs_snapshot()
        all_records = parse_log_records(snapshot["lines"])
        level_counts = summarize_log_levels(all_records)
        records = []
        for record in all_records:
            if level != "ALL" and record["level"] != level:
                continue
            searchable = " ".join(str(value) for value in record.values())
            if search and search.lower() not in searchable.lower():
                continue
            records.append(record)

        total_logs = len(records)
        records.reverse()
        total_pages = max(1, math.ceil(total_logs / per_page))
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        paginated = records[start:start + per_page]

        window_size = 10
        page_window_start = max(1, page - 4)
        page_window_end = min(total_pages, page_window_start + window_size - 1)
        if (page_window_end - page_window_start) < (window_size - 1):
            page_window_start = max(1, page_window_end - window_size + 1)

        return render_template(
            "logs/logs.html",
            logs=paginated,
            page=page,
            total_pages=total_pages,
            page_window_start=page_window_start,
            page_window_end=page_window_end,
            level=level,
            search=search,
            level_counts=level_counts,
            log_read_errors=snapshot["errors"],
            active_page="logs",
        )

    @app.route("/logs/download")
    def download_logs():
        output = []
        anonymizer = AnonymizeFilter(force=True)
        for line in read_all_logs():
            record = type(
                "Record",
                (),
                {"msg": line, "args": (), "getMessage": lambda self: self.msg},
            )()
            anonymizer.filter(record)
            output.append(record.msg)

        if not output:
            output.append("No logs available.\n")

        filename = f"{datetime.now().strftime('%Y-%m-%d')}_vodum-logs-anonymized.log"
        return Response(
            "".join(output),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
